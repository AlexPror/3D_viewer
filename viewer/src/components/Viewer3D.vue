<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import * as THREE from 'three'
import { TrackballControls } from 'three/addons/controls/TrackballControls.js'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js'
import { STLExporter } from 'three/addons/exporters/STLExporter.js'
import { loadStepOrIgesToGlbUrl, getOpenCascade } from '../lib/stepLoader'
import { logger } from '../lib/logger'
import {
  type Model3dComment,
  type Model3dRemarksDocument,
  type Model3dViewState,
  buildModel3dRemarksFile,
  createEmptyModel3dRemarks,
  downloadJsonBlob,
  encodeModel3dRemarksFile,
  formatModel3dRemarksFileName,
  loadModel3dRemarks,
  modelRemarksDocumentKey,
  newModel3dCommentId,
  parseModel3dRemarksBytes,
  saveModel3dRemarks,
  cloneModel3dRemarks,
  normalizeModel3dRemarksDocument,
  type Model3dAnchor3d,
} from '../lib/model3dRemarks'
import {
  type RemarkStatus,
  type RemarkStatusFilter,
  REMARK_STATUS_OPTIONS,
  remarkStatusLabel,
  remarkStatusCssClass,
  normalizeRemarkStatus,
} from '../lib/remarkStatus'
import {
  type ScreenLayerShape,
  type ScreenLayerTool,
  type Model3dScreenImage,
  ensureScreenLayer,
  newScreenLayerImageId,
  viewDirectionAngleDeg,
  SCREEN_LAYER_VIEW_ANGLE_THRESHOLD_DEG,
} from '../lib/model3dScreenLayer'
import Model3dScreenLayerOverlay from './Model3dScreenLayerOverlay.vue'
import ViewerSidebarIcons from './ViewerSidebarIcons.vue'
import {
  type PartCategoryId,
  inferPartCategory,
} from '../lib/partTree'
import { meshPartGroupKey, pickGeometryGroupLabel } from '../lib/meshGeometrySignature'

const containerRef = ref<HTMLDivElement | null>(null)
const isLoading = ref(false)
const headerToolsTab = ref<'viewTools' | 'display' | 'export'>('viewTools')

const props = defineProps<{
  sectionMode?: boolean
  sectionActive?: boolean
  sectionOffset?: number
  measureMode?: boolean
  measureSnapMode?: MeasureSnapMode
  measureType?: MeasureType
}>()

const emit = defineEmits<{
  'section-active': []
  'section-inactive': []
  'section-offset-changed': [value: number]
  'section-mode': []
  'fix-section': []
  'clear-section': []
  'update:sectionOffset': [value: number]
  'measure': []
  'update:measureSnapMode': [value: MeasureSnapMode]
  'update:measureType': [value: MeasureType]
  'clear-measurements': []
  'export-glb': []
  'export-stl': []
  'screenshot-3d': []
  'remarks-dirty': [dirty: boolean]
}>()

let scene: THREE.Scene
let sectionPlane: THREE.Plane | null = null
let currentSectionAxis: 'x' | 'y' | 'z' | null = null
let currentSectionOffset = 0
let camera: THREE.PerspectiveCamera
let renderer: THREE.WebGLRenderer
let controls: InstanceType<typeof TrackballControls>
let meshGroup: THREE.Group
/** Характерный размер загруженной сцены (мм) — для масштаба подписей измерений. */
let loadedSceneCharDim = 1000
let overlayGroup: THREE.Group
let measureGroup: THREE.Group
let highlightGroup: THREE.Group
let axesHelper: THREE.Group | null = null
let groundGrid: THREE.GridHelper | null = null
let ambientLight: THREE.AmbientLight | null = null
let hemiLight: THREE.HemisphereLight | null = null
let keyLight: THREE.DirectionalLight | null = null
let fillLightA: THREE.DirectionalLight | null = null
let fillLightB: THREE.DirectionalLight | null = null
let fillLightC: THREE.DirectionalLight | null = null
let rimLightA: THREE.DirectionalLight | null = null
let rimLightB: THREE.DirectionalLight | null = null
let raycaster: THREE.Raycaster
let mouse: THREE.Vector2
const HOVER_UPDATE_INTERVAL_MS = 80
let hoverDirty = true
let lastHoverUpdateAt = 0
let isCameraInteracting = false
const INTERACTION_PIXEL_RATIO = 1
const SCREENSHOT_PIXEL_RATIO_MIN = 2
const SCREENSHOT_PIXEL_RATIO_MAX = 3
let idlePixelRatio = 1
let lastClipPlaneDist = -1
/** Характерный размер активной (фокусной) модели — для зума и min distance. */
let focusedSceneCharDim = 1000

function screenshotPixelRatio(): number {
  const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1
  return Math.min(
    SCREENSHOT_PIXEL_RATIO_MAX,
    Math.max(SCREENSHOT_PIXEL_RATIO_MIN, dpr * 1.5),
  )
}
const showGroundGrid = ref(true)
let measurementPoints: THREE.Vector3[] = []
let measurementPointNormals: (THREE.Vector3 | null)[] = []
let measurementPointModelIds: (string | null)[] = []
let measurementPointMeshUuids: (string | null)[] = []
let measurementPointLocals: (SavedVec3 | null)[] = []
let measurementPointNormalLocals: (SavedVec3 | null)[] = []
let measurementLine: THREE.Line | null = null
let measurementTriangleLines: THREE.Line[] = []
let measurementPerpLine: THREE.Line | null = null
let measurementCircleMesh: THREE.LineLoop | null = null
let measurementCircleMesh2: THREE.LineLoop | null = null
let measurementArcPathLine: THREE.Line | null = null
/** Геометрии двух плоскостей для режима «расстояние» (в мировых координатах), чтобы подсвечивать их на скриншоте */
let measurementFaceGeometries: THREE.BufferGeometry[] = []
let measurementPlanesGroup: THREE.Group
let savedMeasurementsGroup: THREE.Group
let remarkAnchorsGroup: THREE.Group
/** Подсветка выбранных плоскостей сборки и связей из таблицы (после initScene) */
let assemblyHighlightGroup: THREE.Group | undefined
let worldCoordSystemGroup: THREE.Group | null = null
let measurementLabelEl: HTMLDivElement | null = null
let measurementPerpLabelEl: HTMLDivElement | null = null
let measurementExtraLabelEl: HTMLDivElement | null = null
let measurementLabelEl0: HTMLDivElement | null = null
let measurementLabelEl1: HTMLDivElement | null = null
let measurementLabelEl2: HTMLDivElement | null = null
let hoverTooltipEl: HTMLDivElement | null = null
/** Вторая точка при live-preview (расстояние: 1 клик + движение мыши). */
let measurePreviewPoint: THREE.Vector3 | null = null
let savedMeasurementLabelsLayer: HTMLDivElement | null = null
const savedMeasurementLabelById = new Map<string, HTMLDivElement>()
let lastHoverNormal: THREE.Vector3 | null = null
let lastHoverPoint: THREE.Vector3 | null = null
const measureModeRef = ref(false)
const sectionModeRef = ref(false)
/** Каркас всей сцены (кнопка «Каркас» в отображении). */
const wireframeModeRef = ref(false)
type PartTreeIsolateState = {
  modelId: string
  rowId: string
  meshVisible: Map<string, boolean>
  keepIds: Set<string>
}
const partTreeIsolateState = ref<PartTreeIsolateState | null>(null)
/** Непрозрачность линий каркаса (EdgesGeometry), не граней модели. */
const frameOpacityRef = ref(0.9)
const FRAME_OPACITY_MIN = 0.1
const FRAME_OPACITY_MAX = 1
const FRAME_OPACITY_STEP = 0.05
const WIREFRAME_EDGE_THRESHOLD_DEG = 25
const WIREFRAME_MAX_EDGE_MESHES = 6000
/** Грани невидимы — видны только линии каркаса. */
const WIREFRAME_GHOST_FACE_OPACITY = 0
/** Прозрачность отдельных деталей (ПКМ), по uuid меша. */
const meshUserOpacityByUuid = ref<Record<string, number>>({})
const wireframeFaceMatBackup = new Map<
  THREE.Mesh,
  Array<{ transparent: boolean; opacity: number; depthWrite: boolean }>
>()
const meshRaycastBackup = new Map<THREE.Mesh, THREE.Mesh['raycast']>()
const noopRaycast: THREE.Mesh['raycast'] = () => {}

function clampFrameOpacity(v: number): number {
  return Math.max(FRAME_OPACITY_MIN, Math.min(FRAME_OPACITY_MAX, v))
}

function onFrameOpacityInput(ev: Event) {
  const val = Number((ev.target as HTMLInputElement).value)
  if (Number.isFinite(val)) {
    const next = clampFrameOpacity(val)
    frameOpacityRef.value = next
    if (wireframeModeRef.value) updateWireframeEdgeLineOpacity()
  }
}

function onFrameOpacityWheel(ev: WheelEvent) {
  const delta = ev.deltaY > 0 ? -FRAME_OPACITY_STEP : FRAME_OPACITY_STEP
  const next = clampFrameOpacity(frameOpacityRef.value + delta)
  frameOpacityRef.value = next
  if (wireframeModeRef.value) updateWireframeEdgeLineOpacity()
}

/** Выбранная грань для кнопки «Перпендикулярно» (центр и нормаль в мировой СК). */
let selectedFacePoint: THREE.Vector3 | null = null
let selectedFaceNormal: THREE.Vector3 | null = null
let sectionPlaneMesh: THREE.Mesh | null = null
let sectionPlaneBasePoint: THREE.Vector3 | null = null
let sectionPlaneNormal: THREE.Vector3 | null = null
let sectionPlaneClipNormal: THREE.Vector3 | null = null
let sectionPlaneOffset = 0
const SECTION_OFFSET_MIN = -2000
const SECTION_OFFSET_MAX = 2000
const SECTION_OFFSET_STEP = 10
let animationId: number
export type MeasureSnapMode = 'intersection' | 'vertex' | 'face' | 'edge'
export type MeasureType = 'distance' | 'radius' | 'diameter' | 'arc' | 'hole-center-distance' | 'cad-linear'
let measureSnapMode: MeasureSnapMode = 'intersection'
const measureTypeRef = ref<MeasureType>('distance')
let fileInput: HTMLInputElement | null = null
let loadedFileName: string | null = null

export interface LoadedModelItem {
  id: string
  name: string
  thumbnailDataUrl: string
  /** Модель отображается в сцене (false = только в библиотеке) */
  inScene: boolean
}

type SavedMeasureType = 'distance' | 'radius' | 'diameter' | 'arc' | 'cad-linear'
type SavedVec3 = { x: number; y: number; z: number }
type AssemblyMateType = 'plane' | 'distance' | 'symmetric' | 'coord'
type AssemblyAxis = 'x' | 'y' | 'z'
type AssemblyPlaneSide = 'min' | 'max'
/** Мировые координатные плоскости (пересечение осей X/Y/Z в начале координат). */
type WorldCoordPlaneId = 'xy_pos' | 'xy_neg' | 'xz_pos' | 'xz_neg' | 'yz_pos' | 'yz_neg'

const WORLD_COORD_PLANE_OPTIONS: { id: WorldCoordPlaneId; label: string; hint: string }[] = [
  { id: 'xy_pos', label: 'XY — горизонт (нормаль +Z)', hint: 'Плоскость пола, ось Z вверх' },
  { id: 'xy_neg', label: 'XY — горизонт (нормаль −Z)', hint: 'Плоскость потолка' },
  { id: 'xz_pos', label: 'XZ — фасад (нормаль +Y)', hint: 'Вертикальная плоскость, ось Y вперёд' },
  { id: 'xz_neg', label: 'XZ — фасад (нормаль −Y)', hint: 'Вертикальная плоскость, ось Y назад' },
  { id: 'yz_pos', label: 'YZ — бок (нормаль +X)', hint: 'Вертикальная плоскость, ось X вправо' },
  { id: 'yz_neg', label: 'YZ — бок (нормаль −X)', hint: 'Вертикальная плоскость, ось X влево' },
]
type AssemblyPickTarget =
  | 'source'
  | 'target'
  | 'symBase1'
  | 'symBase2'
  | 'symPart1'
  | 'symPart2'
  | null

type MeshFaceSurfaceKind = 'plane' | 'cylinder' | 'unknown'

interface AssemblyPlaneSelection {
  modelId: string
  localPoint: THREE.Vector3
  point: THREE.Vector3
  /** Меш грани (для разнесения деталей). */
  meshUuid?: string
  meshLocalPoint?: THREE.Vector3
  /** Нормаль в локальной СК модели (wrapper). */
  normal: THREE.Vector3
  surfaceKind?: MeshFaceSurfaceKind
  /** Ось цилиндра в локальной СК (для будущего сопряжения осей). */
  cylinderAxisLocal?: THREE.Vector3
  /** Треугольник выбранной грани в мировых координатах (для подсветки). */
  previewGeometry?: THREE.BufferGeometry
}

type StoredAssemblyVec3 = { x: number; y: number; z: number }

interface StoredAssemblyPlane {
  modelId: string
  localPoint: StoredAssemblyVec3
  normal: StoredAssemblyVec3
}

type StoredAssemblyMate =
  | {
      id: string
      type: 'plane'
      sourceId: string
      targetId: string
      sourcePlane: StoredAssemblyPlane
      targetPlane: StoredAssemblyPlane
    }
  | {
      id: string
      type: 'distance'
      sourceId: string
      targetId: string
      sourcePlane: StoredAssemblyPlane
      targetPlane: StoredAssemblyPlane
      distanceMm: number
    }
  | {
      id: string
      type: 'symmetric'
      sourceId: string
      targetId: string
      base1: StoredAssemblyPlane
      base2: StoredAssemblyPlane
      part1: StoredAssemblyPlane
      part2: StoredAssemblyPlane
    }
  | {
      id: string
      type: 'coord'
      sourceId: string
      sourcePlane: StoredAssemblyPlane
      worldPlane: WorldCoordPlaneId
      distanceMm: number
      flipNormal: boolean
    }

/** Файл проекта сборки: модели по имени файла (как в списке «Модели»). */
interface ExportedAssemblyPlane {
  modelName: string
  localPoint: StoredAssemblyVec3
  normal: StoredAssemblyVec3
}

type ExportedAssemblyMate =
  | {
      id: string
      type: 'plane'
      sourceModelName: string
      targetModelName: string
      sourcePlane: ExportedAssemblyPlane
      targetPlane: ExportedAssemblyPlane
    }
  | {
      id: string
      type: 'distance'
      sourceModelName: string
      targetModelName: string
      sourcePlane: ExportedAssemblyPlane
      targetPlane: ExportedAssemblyPlane
      distanceMm: number
    }
  | {
      id: string
      type: 'symmetric'
      sourceModelName: string
      targetModelName: string
      base1: ExportedAssemblyPlane
      base2: ExportedAssemblyPlane
      part1: ExportedAssemblyPlane
      part2: ExportedAssemblyPlane
    }
  | {
      id: string
      type: 'coord'
      sourceModelName: string
      sourcePlane: ExportedAssemblyPlane
      worldPlane: WorldCoordPlaneId
      distanceMm: number
      flipNormal: boolean
    }

interface AssemblyProjectPartLayerV1 {
  modelName: string
  /** Ключ из meshGeometryGroupKey (geo:… или pid:…). */
  geomKey: string
  layerId: string
  colorOverride?: string
}

interface AssemblyProjectFileV1 {
  format: '3d-viewer-assembly-project'
  version: 1
  savedAt: string
  models: Array<{
    modelName: string
    inScene: boolean
    px: number
    py: number
    pz: number
    rx: number
    ry: number
    rz: number
  }>
  assemblyMates: ExportedAssemblyMate[]
  /** Слои документа (опционально, с версии с поддержкой слоёв). */
  sceneLayers?: Array<{ id: string; name: string; color: string; visible: boolean }>
  partLayers?: AssemblyProjectPartLayerV1[]
}

interface SavedMeasurement {
  id: string
  type: SavedMeasureType
  createdAt: string
  lengthMm: number
  parallelMm: number
  trianglePerpMm: number
  surfacePerpMm: number | null
  p1: SavedVec3
  p2: SavedVec3
  n1: SavedVec3 | null
  n2: SavedVec3 | null
  /** Для устойчивого восстановления после перемещения модели. */
  modelId1?: string | null
  modelId2?: string | null
  /** UUID меша для точки (устойчиво при разнесении деталей). */
  meshUuid1?: string | null
  meshUuid2?: string | null
  p1Local?: SavedVec3 | null
  p2Local?: SavedVec3 | null
  n1Local?: SavedVec3 | null
  n2Local?: SavedVec3 | null
  /** Радиус/диаметр: центр и нормаль в локале модели. */
  centerLocal?: SavedVec3 | null
  centerModelId?: string | null
  centerMeshUuid?: string | null
  centerNormalLocal?: SavedVec3 | null
  radiusMmValue?: number | null
  secondCenterLocal?: SavedVec3 | null
  secondCenterModelId?: string | null
  secondCenterMeshUuid?: string | null
  arcPath?: SavedVec3[] | null
  arcModelId?: string | null
  arcPathLocal?: SavedVec3[] | null
  displayValue?: string | null
  outputPlaneModelId?: string | null
  outputPlaneLocalPoint?: SavedVec3 | null
  outputPlaneLocalNormal?: SavedVec3 | null
  lineOffsetMm?: number | null
}

interface PartColorMetaPart {
  partId: string
  displayName?: string
  name?: string
  material?: string
  category?: string
  defaultColor?: string
}

interface PartColorMetaInstance {
  instanceId: string
  partId: string
  colorOverride?: string
}

interface PartColorMetaBinding {
  meshNode: string
  instanceId?: string
  partId?: string
}

interface PartColorMeta {
  version?: number
  parts: PartColorMetaPart[]
  instances: PartColorMetaInstance[]
  meshBindings: PartColorMetaBinding[]
}

const MAX_MODELS_IN_SCENE = 8
const MAX_FILES_SELECT = 5
const THUMBNAIL_PLACEHOLDER = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="160" height="120"><rect fill="%23252" width="160" height="120"/><text x="80" y="60" fill="%238a9bb5" text-anchor="middle" font-size="12">…</text></svg>'

const loadedModels = ref<LoadedModelItem[]>([])
const measurementHistory = ref<SavedMeasurement[]>([])
const selectedMeasurementId = ref<string | null>(null)
const originalMaterials = new WeakMap<THREE.Mesh, THREE.Material | THREE.Material[]>()
const preservePartColors = ref(true)
const autoColorizeSegments = ref(true)
const overlayEnabled = ref(false)
const overlayOpacity = ref(0.7)
const OVERLAY_OPACITY_MIN = 0.05
const OVERLAY_OPACITY_MAX = 1
const OVERLAY_OPACITY_STEP = 0.01
const explodeAmount = ref(0)
const EXPLODE_MIN = 0
/** 0…100 = процент от максимального габарита модели (макс. сторона bbox, мм). */
const EXPLODE_MAX = 100
const EXPLODE_STEP = 1
const overlayGroupByModelId = new Map<string, THREE.Group>()
const overlaySourceByModelId = new Map<string, THREE.Group>()
const partContextMenuOpen = ref(false)
const partContextMenuX = ref(0)
const partContextMenuY = ref(0)
const contextMenuTargetModelId = ref<string | null>(null)
let contextMenuTargetPart: THREE.Object3D | null = null
const contextMenuCanShow = ref(false)
const contextMenuTargetIsHidden = ref(false)
let rightMouseDown = false
let rightMouseDragged = false
let rightMouseDownX = 0
let rightMouseDownY = 0
let pendingOrbitPivot: THREE.Vector3 | null = null
let orbitPivotAppliedThisGesture = false
const ORBIT_PIVOT_MIN_SHIFT_MM = 8
const RIGHT_DRAG_THRESHOLD_PX = 6
interface ComponentTreeNode {
  id: string
  label: string
  visible: boolean
  targetIds: string[]
  children: ComponentTreeNode[]
  nodeKind?: 'category' | 'group'
  categoryId?: PartCategoryId
}
interface ComponentTreeRow {
  id: string
  label: string
  visible: boolean
  targetIds: string[]
  depth: number
  nodeKind?: 'category' | 'group'
}
const componentTreeByModel = ref<Record<string, ComponentTreeNode[]>>({})
const selectedComponentRowId = ref<string | null>(null)
/** Мультивыбор деталей: ключ `${modelId}:${rowId}`. */
const selectedPartRowKeys = ref<Set<string>>(new Set())
const highlightedComponentMeshes = new Set<THREE.Mesh>()
type SelectionMaterialBackup = { color: THREE.Color; emissive: THREE.Color; emissiveIntensity: number }
const selectionMaterialBackups = new Map<THREE.Mesh, SelectionMaterialBackup[]>()
const PART_SELECTION_TINT = new THREE.Color(0x7fd4ff)
const PART_SELECTION_EMISSIVE = 0x2a8fd4
const PART_SELECTION_EMISSIVE_INTENSITY = 1.2
const expandedCategoryIds = ref<Record<string, boolean>>({})
let hiddenOutlineGroup: THREE.Group
const hiddenOutlineByComponentId = new Map<string, THREE.Box3Helper>()
const assemblyPanelOpen = ref(false)

/** Панель как в КОМПАС: дерево | параметры | слои | библиотека. */
type LeftSidebarTab = 'tree' | 'params' | 'layers' | 'library'
type ParamsSubTab = 'assembly' | 'measurements' | 'selection' | 'remarks'
type LegacyLeftTab = 'models' | 'assembly' | 'measurements' | 'remarks'
const leftSidebarTab = ref<LeftSidebarTab>('tree')
const paramsSubTab = ref<ParamsSubTab>('assembly')

const isRemarksPanelActive = computed(
  () => leftSidebarTab.value === 'params' && paramsSubTab.value === 'remarks',
)

const libraryModels = computed(() => loadedModels.value.filter((m) => !m.inScene))

function setLeftSidebarTab(tab: LeftSidebarTab | LegacyLeftTab) {
  switch (tab) {
    case 'models':
    case 'tree':
      leftSidebarTab.value = 'tree'
      break
    case 'assembly':
      leftSidebarTab.value = 'params'
      paramsSubTab.value = 'assembly'
      assemblyPanelOpen.value = true
      break
    case 'measurements':
      leftSidebarTab.value = 'params'
      paramsSubTab.value = 'measurements'
      break
    case 'remarks':
      leftSidebarTab.value = 'params'
      paramsSubTab.value = 'remarks'
      break
    default:
      leftSidebarTab.value = tab
      break
  }
}

function setParamsSubTab(sub: ParamsSubTab) {
  paramsSubTab.value = sub
  leftSidebarTab.value = 'params'
  if (sub === 'assembly') assemblyPanelOpen.value = true
}

function onAssemblyHeaderClick() {
  setLeftSidebarTab('assembly')
}

function onMeasureHeaderClick() {
  setLeftSidebarTab('measurements')
  emit('measure')
}

/** Слои 3D-сцены (аналог слоёв документа). */
interface SceneLayer3d {
  id: string
  name: string
  color: string
  visible: boolean
}
const sceneLayers3d = ref<SceneLayer3d[]>([
  { id: 'layer-0', name: '0 — Основной', color: '#e8eef8', visible: true },
])
const meshLayerByUuid = ref<Record<string, string>>({})
const layerColorOverrideByUuid = ref<Record<string, string>>({})
const selectedLayerAssignId = ref('layer-0')
const partFocusActive = ref(false)
/** Затемнять остальные детали при выделении (выкл. по умолчанию — иначе тормозит на больших сборках). */
const partIsolateDimOthers = ref(false)

const boxSelectRect = ref<{
  left: number
  top: number
  width: number
  height: number
  mode: 'window' | 'crossing'
} | null>(null)
let boxSelectDrag: { startX: number; startY: number; additive: boolean } | null = null
let didBoxSelect = false

const dimmedMeshBackups = new Map<
  THREE.Mesh,
  { material: THREE.Material | THREE.Material[]; visible: boolean }
>()
let partFocusEdgeGroup: THREE.Group
const sharedGhostMaterial = new THREE.MeshLambertMaterial({
  color: 0x8a929e,
  transparent: true,
  opacity: 0.2,
  depthWrite: false,
})

const remarksDoc = ref<Model3dRemarksDocument | null>(null)
const selectedRemarkId = ref<string | null>(null)
const remarksDirty = ref(false)
let remarksDirtyBaseline = '[]'

const primaryModelFileName = computed(() => {
  const inScene = loadedModels.value.filter((m) => m.inScene)
  if (inScene.length > 0) return inScene[inScene.length - 1].name
  return loadedFileName?.trim() || ''
})

const remarkStatusFilter = ref<RemarkStatusFilter>('all')

const remarkList = computed(() => remarksDoc.value?.comments ?? [])

const filteredRemarkList = computed(() => {
  const list = remarkList.value
  if (remarkStatusFilter.value === 'all') return list
  return list.filter((c) => normalizeRemarkStatus(c.status) === remarkStatusFilter.value)
})

const selectedRemark = computed(() => {
  if (!selectedRemarkId.value || !remarksDoc.value) return null
  return remarksDoc.value.comments.find((c) => c.id === selectedRemarkId.value) ?? null
})

const remarkAnchorPickMode = ref(false)
const remarkScreenTool = ref<ScreenLayerTool>('select')
const remarkScreenSelectedImageId = ref<string | null>(null)
const screenLayerOverlayRef = ref<InstanceType<typeof Model3dScreenLayerOverlay> | null>(null)
const remarkScreenColor = ref('#cc0000')
const remarkScreenSelectedShapeId = ref<string | null>(null)
const remarkViewAngleDeg = ref(0)

const remarkScreenLayerVisible = computed(
  () =>
    isRemarksPanelActive.value &&
    !!selectedRemark.value &&
    remarkViewAngleDeg.value <= SCREEN_LAYER_VIEW_ANGLE_THRESHOLD_DEG,
)

const remarkScreenLayerEditable = computed(
  () => remarkScreenLayerVisible.value && !remarkAnchorPickMode.value && !!selectedRemark.value,
)

const selectedRemarkScreenShapes = computed({
  get: () => selectedRemark.value?.screenLayer?.shapes ?? [],
  set: (shapes: ScreenLayerShape[]) => {
    onRemarkScreenShapesUpdate(shapes)
  },
})

const selectedRemarkScreenImages = computed({
  get: () => selectedRemark.value?.images ?? [],
  set: (images: Model3dScreenImage[]) => {
    onRemarkScreenImagesUpdate(images)
  },
})

function syncRemarksDirtyFlag() {
  const dirty = JSON.stringify(remarksDoc.value?.comments ?? []) !== remarksDirtyBaseline
  remarksDirty.value = dirty
  emit('remarks-dirty', dirty)
}

function markRemarksChanged() {
  syncRemarksDirtyFlag()
  if (remarksDoc.value) {
    void saveModel3dRemarks(remarksDoc.value).catch((e) => logger.warn('Viewer3D', 'Автосохранение замечаний 3D', e))
  }
}

function captureCurrentViewState(): Model3dViewState | null {
  if (!camera || !controls) return null
  const hiddenModelIds = loadedModels.value.filter((m) => !m.inScene).map((m) => m.id)
  return {
    camera: {
      position: [camera.position.x, camera.position.y, camera.position.z],
      target: [controls.target.x, controls.target.y, controls.target.z],
      up: [camera.up.x, camera.up.y, camera.up.z],
      fov: camera.fov,
    },
    hiddenModelIds,
  }
}

function applyViewState(vs: Model3dViewState) {
  if (!camera || !controls) return
  camera.position.set(vs.camera.position[0], vs.camera.position[1], vs.camera.position[2])
  controls.target.set(vs.camera.target[0], vs.camera.target[1], vs.camera.target[2])
  camera.up.set(vs.camera.up[0], vs.camera.up[1], vs.camera.up[2])
  camera.fov = vs.camera.fov
  camera.updateProjectionMatrix()
  controls.update()
}

async function initRemarksForCurrentModel() {
  const name = primaryModelFileName.value
  if (!name) {
    remarksDoc.value = null
    remarksDirtyBaseline = '[]'
    remarksDirty.value = false
    emit('remarks-dirty', false)
    selectedRemarkId.value = null
    return
  }
  const key = modelRemarksDocumentKey(name)
  const loaded = await loadModel3dRemarks(key)
  const base = loaded ?? createEmptyModel3dRemarks(name)
  remarksDoc.value = normalizeModel3dRemarksDocument({ ...base, modelKey: key, modelFileName: name })
  remarksDirtyBaseline = JSON.stringify(remarksDoc.value.comments)
  remarksDirty.value = false
  emit('remarks-dirty', false)
  selectedRemarkId.value = null
}

function addRemarkFromCurrentView() {
  const name = primaryModelFileName.value
  if (!name) {
    window.alert('Сначала загрузите 3D-модель в сцену.')
    return
  }
  const vs = captureCurrentViewState()
  if (!vs) return
  if (!remarksDoc.value) remarksDoc.value = createEmptyModel3dRemarks(name)
  const title = window.prompt('Название замечания:', `Замечание ${remarkList.value.length + 1}`)
  if (title === null) return
  const comment: Model3dComment = {
    id: newModel3dCommentId(),
    parentId: null,
    title: title.trim() || `Замечание ${remarkList.value.length + 1}`,
    description: '',
    status: 'open',
    createdAt: new Date().toISOString(),
    viewState: vs,
    screenLayer: { shapes: [] },
    images: [],
  }
  remarksDoc.value.comments.push(comment)
  selectedRemarkId.value = comment.id
  remarkScreenTool.value = 'select'
  remarkScreenSelectedShapeId.value = null
  remarkScreenSelectedImageId.value = null
  markRemarksChanged()
  setLeftSidebarTab('remarks')
}

function selectRemark(commentId: string) {
  selectedRemarkId.value = commentId
  selectedMeasurementId.value = null
  remarkScreenSelectedShapeId.value = null
  remarkScreenSelectedImageId.value = null
  const c = remarksDoc.value?.comments.find((x) => x.id === commentId)
  if (c?.viewState) applyViewState(c.viewState)
  ensureSelectedRemarkLayers()
  rebuildRemarkAnchorMarkers()
  updateRemarkViewAngle()
}

function deleteRemarkById(id: string, confirmDelete = true) {
  if (!remarksDoc.value) return
  const idx = remarksDoc.value.comments.findIndex((c) => c.id === id)
  if (idx < 0) return
  if (confirmDelete && !window.confirm('Удалить это замечание?')) return
  remarksDoc.value.comments.splice(idx, 1)
  if (selectedRemarkId.value === id) {
    selectedRemarkId.value = null
    remarkScreenSelectedShapeId.value = null
    remarkScreenSelectedImageId.value = null
  }
  markRemarksChanged()
  rebuildRemarkAnchorMarkers()
}

function deleteSelectedRemark() {
  if (!selectedRemarkId.value) return
  deleteRemarkById(selectedRemarkId.value, true)
}

function restoreSelectedRemarkView() {
  const c = remarksDoc.value?.comments.find((x) => x.id === selectedRemarkId.value)
  if (c?.viewState) {
    applyViewState(c.viewState)
    updateRemarkViewAngle()
  }
}

function updateSelectedRemarkStatus(status: RemarkStatus) {
  const c = selectedRemark.value
  if (!c) return
  c.status = status
  markRemarksChanged()
}

function updateSelectedRemarkDescription(description: string) {
  const c = selectedRemark.value
  if (!c) return
  c.description = description
  markRemarksChanged()
}

function ensureSelectedRemarkLayers() {
  const c = selectedRemark.value
  if (!c) return
  if (!c.screenLayer) c.screenLayer = ensureScreenLayer()
  if (!c.images) c.images = []
}

function onRemarkScreenShapesUpdate(shapes: ScreenLayerShape[]) {
  const c = selectedRemark.value
  if (!c) return
  ensureSelectedRemarkLayers()
  c.screenLayer!.shapes = shapes
  markRemarksChanged()
}

function onRemarkScreenImagesUpdate(images: Model3dScreenImage[]) {
  const c = selectedRemark.value
  if (!c) return
  c.images = images
  markRemarksChanged()
}

function toggleRemarkAnchorPick() {
  remarkAnchorPickMode.value = !remarkAnchorPickMode.value
}

function clearSelectedRemarkAnchor() {
  const c = selectedRemark.value
  if (!c?.anchor3d) return
  c.anchor3d = undefined
  markRemarksChanged()
  rebuildRemarkAnchorMarkers()
}

function anchorWorldPoint(anchor: Model3dAnchor3d): THREE.Vector3 | null {
  const g = modelGroupsById.get(anchor.modelId)
  if (!g) return null
  g.updateMatrixWorld(true)
  return new THREE.Vector3(anchor.pointLocal.x, anchor.pointLocal.y, anchor.pointLocal.z).applyMatrix4(g.matrixWorld)
}

function remarkMarkerRadius(): number {
  if (!meshGroup?.children.length) return 3
  const box = new THREE.Box3().setFromObject(meshGroup)
  const s = box.getSize(new THREE.Vector3())
  return Math.max(0.5, Math.max(s.x, s.y, s.z) * 0.006)
}

function rebuildRemarkAnchorMarkers() {
  if (!remarkAnchorsGroup) return
  while (remarkAnchorsGroup.children.length) {
    const ch = remarkAnchorsGroup.children[0]
    remarkAnchorsGroup.remove(ch)
    if (ch instanceof THREE.Mesh) {
      ch.geometry.dispose()
      const m = ch.material
      if (Array.isArray(m)) m.forEach((x) => x.dispose())
      else m.dispose()
    }
  }
  if (leftSidebarTab.value !== 'remarks') return
  const anchor = selectedRemark.value?.anchor3d
  if (!anchor) return
  const wp = anchorWorldPoint(anchor)
  if (!wp) return
  const r = remarkMarkerRadius()
  const geo = new THREE.SphereGeometry(r, 14, 14)
  const mat = new THREE.MeshStandardMaterial({ color: 0xf97316, emissive: 0x9a3412, emissiveIntensity: 0.35 })
  const mesh = new THREE.Mesh(geo, mat)
  mesh.position.copy(wp)
  remarkAnchorsGroup.add(mesh)
}

function pickRemarkAnchorFromHit(hit: THREE.Intersection) {
  const c = selectedRemark.value
  if (!c) return
  const wrap = findWrapperGroup(hit.object)
  const modelId = String(wrap?.userData?.modelId ?? '')
  if (!modelId || !wrap) {
    window.alert('Кликните по детали в сцене.')
    return
  }
  wrap.updateMatrixWorld(true)
  const inv = wrap.matrixWorld.clone().invert()
  const local = hit.point.clone().applyMatrix4(inv)
  const mesh = hit.object as THREE.Mesh
  const normalLocal = hit
    .face!.normal.clone()
    .transformDirection(mesh.matrixWorld)
    .transformDirection(inv)
    .normalize()
  c.anchor3d = {
    modelId,
    pointLocal: { x: local.x, y: local.y, z: local.z },
    normalLocal: { x: normalLocal.x, y: normalLocal.y, z: normalLocal.z },
  }
  remarkAnchorPickMode.value = false
  markRemarksChanged()
  rebuildRemarkAnchorMarkers()
}

function updateRemarkViewAngle() {
  const c = selectedRemark.value
  if (!c || !camera || !controls) {
    remarkViewAngleDeg.value = 0
    return
  }
  const vs = c.viewState
  remarkViewAngleDeg.value = viewDirectionAngleDeg(
    [camera.position.x, camera.position.y, camera.position.z],
    [controls.target.x, controls.target.y, controls.target.z],
    vs.camera.position,
    vs.camera.target,
  )
}

function insertRemarkScreenImage() {
  const c = selectedRemark.value
  if (!c) return
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/*'
  input.onchange = () => {
    const file = input.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      ensureSelectedRemarkLayers()
      const dataUrl = typeof reader.result === 'string' ? reader.result : ''
      if (!dataUrl) return
      const newId = newScreenLayerImageId()
      c.images!.push({
        id: newId,
        file: file.name,
        dataUrl,
        x: 0.08,
        y: 0.08,
        w: 0.35,
        h: 0.28,
      })
      remarkScreenSelectedImageId.value = newId
      remarkScreenSelectedShapeId.value = null
      remarkScreenTool.value = 'select'
      markRemarksChanged()
    }
    reader.readAsDataURL(file)
  }
  input.click()
}

function deleteSelectedScreenMarkup() {
  screenLayerOverlayRef.value?.deleteSelected()
}

watch(leftSidebarTab, (tab) => {
  if (tab !== 'params' || paramsSubTab.value !== 'remarks') {
    remarkAnchorPickMode.value = false
    rebuildRemarkAnchorMarkers()
  }
})

watch([selectedRemarkId, () => selectedRemark.value?.anchor3d, leftSidebarTab], () => {
  rebuildRemarkAnchorMarkers()
})

async function saveModel3dRemarksToFile(): Promise<{ ok: boolean; fileName?: string }> {
  if (!remarksDoc.value || !primaryModelFileName.value) return { ok: false }
  try {
    const file = buildModel3dRemarksFile(remarksDoc.value)
    const fileName = formatModel3dRemarksFileName(primaryModelFileName.value)
    downloadJsonBlob(encodeModel3dRemarksFile(file), fileName)
    await saveModel3dRemarks(remarksDoc.value)
    remarksDirtyBaseline = JSON.stringify(remarksDoc.value.comments)
    remarksDirty.value = false
    emit('remarks-dirty', false)
    return { ok: true, fileName }
  } catch (e) {
    logger.error('Viewer3D', 'Сохранение замечаний 3D', e)
    return { ok: false }
  }
}

function importModel3dRemarksFile() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json,application/json'
  input.onchange = async () => {
    const file = input.files?.[0]
    if (!file || !primaryModelFileName.value) return
    const parsed = parseModel3dRemarksBytes(await file.arrayBuffer())
    if (!parsed) {
      window.alert('Не удалось прочитать файл замечаний 3D.')
      return
    }
    const key = modelRemarksDocumentKey(primaryModelFileName.value)
    remarksDoc.value = normalizeModel3dRemarksDocument({
      ...cloneModel3dRemarks(parsed.remarks),
      modelKey: key,
      modelFileName: primaryModelFileName.value,
    })
    markRemarksChanged()
    logger.info('Viewer3D', `Замечания 3D загружены: ${file.name}`)
  }
  input.click()
}

async function confirmDiscardModel3dRemarksAsync(): Promise<boolean> {
  if (!remarksDirty.value) return true
  const saveFirst = window.confirm(
    'Есть несохранённые замечания 3D.\n\nOK — сохранить JSON на диск\nОтмена — другое действие',
  )
  if (saveFirst) {
    const r = await saveModel3dRemarksToFile()
    return r.ok
  }
  const discard = window.confirm('Продолжить без сохранения JSON на диск? Черновик останется в браузере.')
  return discard
}

watch(primaryModelFileName, () => {
  void initRemarksForCurrentModel()
})

/** Активная модель для кнопок панели, копирования трансформа и удаления */
const focusedModelId = ref<string | null>(null)
/** Развёрнутые узлы дерева моделей (аккордеон). */
const expandedModelIds = ref<Record<string, boolean>>({})
/** Закреплённые в сцене модели не перетаскиваются и не вращаются ЛКМ */
const pinnedByModelId = ref<Record<string, boolean>>({})
/** Режим ЛКМ: вращение выбранной модели вокруг центра габарита (оси X и Y мира). */
const modelRotateMode = ref(false)
/** Размещение модели в сборке: следует за курсором, фиксация кликом или по координатам. */
const placementActive = ref(false)
const placementModelId = ref<string | null>(null)
const placementPosMm = ref({ x: 0, y: 0, z: 0 })
const placementStatusHint = ref('')
let placementAnchorLocal = new THREE.Vector3()
let placementCancelRemovesFromScene = false
const placementPickPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0)
const placementPickPoint = new THREE.Vector3()
const assemblyMateType = ref<AssemblyMateType>('plane')
const assemblySourceModelId = ref('')
const assemblyTargetModelId = ref('')
const assemblyAxis = ref<AssemblyAxis>('x')
const assemblySourceSide = ref<AssemblyPlaneSide>('max')
const assemblyTargetSide = ref<AssemblyPlaneSide>('min')
const assemblyDistanceMm = ref(0)
const assemblyCoordWorldPlane = ref<WorldCoordPlaneId>('xy_pos')
const assemblyCoordFlipNormal = ref(false)
const showWorldCoordSystem = ref(true)
const worldCoordSystemExpanded = ref(true)
const assemblyStatus = ref('')
const assemblyPickTarget = ref<AssemblyPickTarget>(null)
const assemblySourcePlane = ref<AssemblyPlaneSelection | null>(null)
const assemblyTargetPlane = ref<AssemblyPlaneSelection | null>(null)
/** Симметрия по ширине: две плоскости базы (опорная модель) и две плоскости детали (источник). */
const assemblySymBase1 = ref<AssemblyPlaneSelection | null>(null)
const assemblySymBase2 = ref<AssemblyPlaneSelection | null>(null)
const assemblySymPart1 = ref<AssemblyPlaneSelection | null>(null)
const assemblySymPart2 = ref<AssemblyPlaneSelection | null>(null)
const assemblyMates = ref<StoredAssemblyMate[]>([])
/** Выбранная строка в таблице связей — подсветка зафиксированных плоскостей. */
const selectedAssemblyMateId = ref<string | null>(null)
const modelGroupsById = new Map<string, THREE.Group>()
const visibleAssemblyModels = computed(() => loadedModels.value.filter((m) => m.inScene))
const assemblySourcePlaneText = computed(() =>
  assemblySourcePlane.value
    ? `${loadedModels.value.find((m) => m.id === assemblySourcePlane.value!.modelId)?.name ?? assemblySourcePlane.value.modelId}`
    : 'не выбрана'
)
const assemblyTargetPlaneText = computed(() =>
  assemblyTargetPlane.value
    ? `${loadedModels.value.find((m) => m.id === assemblyTargetPlane.value!.modelId)?.name ?? assemblyTargetPlane.value.modelId}`
    : 'не выбрана'
)
function assemblyPlaneShortLabel(p: AssemblyPlaneSelection | null): string {
  if (!p) return 'не выбрана'
  const name = loadedModels.value.find((m) => m.id === p.modelId)?.name ?? p.modelId
  return `${name}`
}
const cadLinearPlane1Text = computed(() => assemblyPlaneShortLabel(cadLinearPlane1.value))
const cadLinearPlane2Text = computed(() => assemblyPlaneShortLabel(cadLinearPlane2.value))
const cadLinearDisplayPlaneText = computed(() => assemblyPlaneShortLabel(cadLinearDisplayPlane.value))
const linearMeasurementRows = computed(() => measurementHistory.value.filter((m) => m.type === 'cad-linear'))
const assemblySymBase1Text = computed(() => assemblyPlaneShortLabel(assemblySymBase1.value))
const assemblySymBase2Text = computed(() => assemblyPlaneShortLabel(assemblySymBase2.value))
const assemblySymPart1Text = computed(() => assemblyPlaneShortLabel(assemblySymPart1.value))
const assemblySymPart2Text = computed(() => assemblyPlaneShortLabel(assemblySymPart2.value))
const savedCameraPosition = new THREE.Vector3(500, 400, 500)
const savedCameraTarget = new THREE.Vector3(0, 0, 0)

const DEFAULT_COLOR = 0x888888
const DEFAULT_SPECULAR = 0x222222

const MODEL_COLOR_LIGHT = 0xf2f4f6
/** Один светло-серый для модели (на 50% светлее MODEL_COLOR_LIGHT). */
const MODEL_COLOR_SINGLE = 0xf9f9fa
const TINT_BRIGHTNESS_MIN = 0.65
const TINT_BRIGHTNESS_MAX = 2.03
const TINT_BRIGHTNESS_STEP = 0.05
const COLOR_VIVIDNESS_MIN = 0.45
const COLOR_VIVIDNESS_MAX = 1
const COLOR_VIVIDNESS_STEP = 0.05
const tintBrightness = ref(TINT_BRIGHTNESS_MAX)
const colorVividness = ref(COLOR_VIVIDNESS_MAX)
const sceneBackgroundHex = ref('#ffffff')
const extraFillLightsEnabled = ref(true)
const extraRimLightsEnabled = ref(true)
const settingsModalOpen = ref(false)
const shadingMode = ref<'lit' | 'unlit'>('unlit')
const lightPreset = ref<'engineering' | 'soft'>('engineering')
/** STEP/GLB из WASM часто в метрах; если max < порога — масштабируем в мм. */
const METERS_TO_MM_SCALE = 1000
const METERS_LIKELY_MAX_AXIS = 500
const sceneSurfaceAreaMm2 = ref<number | null>(null)
const sceneVolumeMm3 = ref<number | null>(null)
const sceneTriangles = ref<number>(0)
const isMetricsCalculating = ref(false)
let metricsJobSeq = 0

/** Настройки мыши/камеры: дистанция и скорость. */
const mouseMaxDistance = ref(50000)
const mouseMinDistance = ref(10)
const mouseZoomSpeed = ref(0.032)
const mouseInvertWheel = ref(false)
const mouseRotateSpeed = ref(6.4)
const mousePanSpeed = ref(2)
const mouseDamping = ref(0.22)
const mouseZoomGestureMs = ref(450)
/** Левая кнопка: перемещение модели в сцене (перетаскивание детали) */
const leftButtonMoveModel = ref(false)
const autoNavLimitsEnabled = ref(true)

const CAD_MOUSE_LIMITS = {
  minDistanceMin: 1,
  minDistanceMax: 600,
  maxDistanceMin: 300,
  maxDistanceMax: 500000,
  zoomSpeedMin: 0.01,
  zoomSpeedMax: 0.09,
  rotateSpeedMin: 2.2,
  rotateSpeedMax: 8.8,
  panSpeedMin: 0.7,
  panSpeedMax: 3.5,
  dampingMin: 0.12,
  dampingMax: 0.4,
  zoomGestureMsMin: 180,
  zoomGestureMsMax: 900,
  minZoomGap: 50,
} as const

function clampNumber(v: number, min: number, max: number, fallback: number) {
  if (!Number.isFinite(v)) return fallback
  return Math.min(max, Math.max(min, v))
}

function normalizeMouseSettings() {
  const minD = clampNumber(
    mouseMinDistance.value,
    CAD_MOUSE_LIMITS.minDistanceMin,
    CAD_MOUSE_LIMITS.minDistanceMax,
    10
  )
  const maxD = clampNumber(
    mouseMaxDistance.value,
    CAD_MOUSE_LIMITS.maxDistanceMin,
    CAD_MOUSE_LIMITS.maxDistanceMax,
    50000
  )
  mouseMinDistance.value = minD
  mouseMaxDistance.value = Math.max(maxD, minD + CAD_MOUSE_LIMITS.minZoomGap)
  mouseZoomSpeed.value = clampNumber(mouseZoomSpeed.value, CAD_MOUSE_LIMITS.zoomSpeedMin, CAD_MOUSE_LIMITS.zoomSpeedMax, 0.032)
  mouseRotateSpeed.value = clampNumber(mouseRotateSpeed.value, CAD_MOUSE_LIMITS.rotateSpeedMin, CAD_MOUSE_LIMITS.rotateSpeedMax, 6.4)
  mousePanSpeed.value = clampNumber(mousePanSpeed.value, CAD_MOUSE_LIMITS.panSpeedMin, CAD_MOUSE_LIMITS.panSpeedMax, 2)
  mouseDamping.value = clampNumber(mouseDamping.value, CAD_MOUSE_LIMITS.dampingMin, CAD_MOUSE_LIMITS.dampingMax, 0.22)
  mouseZoomGestureMs.value = Math.round(
    clampNumber(mouseZoomGestureMs.value, CAD_MOUSE_LIMITS.zoomGestureMsMin, CAD_MOUSE_LIMITS.zoomGestureMsMax, 450)
  )
}

function boxCharDim(box: THREE.Box3): number {
  const size = box.getSize(new THREE.Vector3())
  const sx = size.x
  const sy = size.y
  const sz = size.z
  const maxDim = Math.max(sx, sy, sz, 1e-9)
  const minDim = Math.min(sx, sy, sz)
  const isFlat = maxDim > 1e-6 && minDim / maxDim < 0.03
  if (!isFlat) return maxDim
  const thinAxis = sx <= sy && sx <= sz ? 0 : sy <= sx && sy <= sz ? 1 : 2
  return thinAxis === 0 ? Math.max(sy, sz) : thinAxis === 1 ? Math.max(sx, sz) : Math.max(sx, sy)
}

function getFullSceneBox(): THREE.Box3 | null {
  if (!meshGroup || meshGroup.children.length === 0) return null
  const b = new THREE.Box3().setFromObject(meshGroup)
  return b.isEmpty() ? null : b
}

function getFocusedModelBox(): THREE.Box3 | null {
  const id = focusedModelId.value
  if (!id) return null
  return getAssemblyModelBox(id)
}

function updateCameraClipPlanes(force = false) {
  if (!(camera instanceof THREE.PerspectiveCamera) || !controls) return
  const dist = camera.position.distanceTo(controls.target)
  if (!force && lastClipPlaneDist > 0 && Math.abs(dist - lastClipPlaneDist) / lastClipPlaneDist < 0.04) return
  lastClipPlaneDist = dist
  const sceneBox = getFullSceneBox()
  const focusBox = getFocusedModelBox()
  let sceneSpan = loadedSceneCharDim || 1000
  let focusSpan = focusedSceneCharDim || sceneSpan
  if (sceneBox) {
    const s = sceneBox.getSize(new THREE.Vector3())
    sceneSpan = Math.max(s.x, s.y, s.z, 1)
  }
  if (focusBox) {
    const fs = focusBox.getSize(new THREE.Vector3())
    focusSpan = Math.max(fs.x, fs.y, fs.z, 1)
  }
  const span = Math.max(focusSpan, sceneSpan * 0.35)
  camera.near = Math.max(0.5, Math.min(span * 0.002, dist / 800))
  camera.far = Math.max(500_000, sceneSpan * 50, dist * 12)
  camera.updateProjectionMatrix()
}

function clampCameraToNavigationLimits() {
  if (!camera || !controls) return
  const dist = camera.position.distanceTo(controls.target)
  const minD = mouseMinDistance.value
  const maxD = mouseMaxDistance.value
  if (dist > maxD * 1.02) {
    const dir = camera.position.clone().sub(controls.target).normalize()
    camera.position.copy(controls.target).add(dir.multiplyScalar(maxD * 0.98))
    lastClipPlaneDist = -1
  } else if (dist < minD * 0.98) {
    const dir = camera.position.clone().sub(controls.target).normalize()
    camera.position.copy(controls.target).add(dir.multiplyScalar(minD))
    lastClipPlaneDist = -1
  }
}

function applyAutoNavigationLimits() {
  if (!autoNavLimitsEnabled.value) return
  const sceneBox = getFullSceneBox()
  const focusBox = getFocusedModelBox() ?? getReferenceSceneBox() ?? sceneBox
  if (!focusBox && !sceneBox) return
  const focusChar = boxCharDim(focusBox ?? sceneBox!)
  const sceneChar = sceneBox ? boxCharDim(sceneBox) : focusChar
  focusedSceneCharDim = focusChar
  const autoMin = Math.max(focusChar * 1e-4, Math.min(focusChar * 0.002, 120))
  const autoMax = Math.min(
    CAD_MOUSE_LIMITS.maxDistanceMax,
    Math.max(autoMin + CAD_MOUSE_LIMITS.minZoomGap + 80, focusChar * 14, sceneChar * 32),
  )
  mouseMinDistance.value = Number(autoMin.toFixed(1))
  mouseMaxDistance.value = Number(autoMax.toFixed(1))
  applyMouseSettings()
  clampCameraToNavigationLimits()
  updateCameraClipPlanes(true)
}

function applyMouseSettings() {
  normalizeMouseSettings()
  if (!controls) return
  controls.minDistance = mouseMinDistance.value
  controls.maxDistance = mouseMaxDistance.value
  controls.rotateSpeed = mouseRotateSpeed.value
  controls.panSpeed = mousePanSpeed.value
  controls.dynamicDampingFactor = mouseDamping.value
}

function applyModelTint() {
  if (!meshGroup) return
  const base = new THREE.Color(MODEL_COLOR_SINGLE)
  const hsl = { h: 0, s: 0, l: 0 }
  base.getHSL(hsl)
  // В "светлом" режиме оставляем небольшой запас контраста, чтобы не терялись грани.
  const maxLightness = shadingMode.value === 'unlit' ? 0.9 : 1
  const lightness = Math.max(0, Math.min(maxLightness, hsl.l * tintBrightness.value))
  const colorHex = new THREE.Color().setHSL(hsl.h, hsl.s, lightness).getHex()
  meshGroup.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh) || !obj.material) return
    if (preservePartColors.value && (obj.userData?.lockPartColor || obj.userData?.hasImportedColor)) return
    const arr = Array.isArray(obj.material) ? obj.material : [obj.material]
    arr.forEach((m: THREE.Material) => {
      if ('color' in m) (m as THREE.Material & { color: THREE.Color }).color.setHex(colorHex)
    })
  })
}

/** Светло-серые дефолты GLB/вьюера — не считаем «цветом из файла». */
function isNeutralImportedHex(hex: string): boolean {
  const h = hex.replace(/^#/, '').toLowerCase()
  if (
    h === 'ffffff' ||
    h === 'f9f9fa' ||
    h === 'f2f4f6' ||
    h === 'cccccc' ||
    h === 'c0c0c0' ||
    h === '808080' ||
    h === 'b0b0b0'
  ) {
    return true
  }
  const c = new THREE.Color(`#${h}`)
  const hsl = { h: 0, s: 0, l: 0 }
  c.getHSL(hsl)
  return hsl.s < 0.12 && hsl.l > 0.72
}

function meshPrimaryHex(obj: THREE.Mesh): string | null {
  const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
  for (const m of mats) {
    if ('color' in m) {
      const c = (m as THREE.Material & { color: THREE.Color }).color
      return `#${c.getHexString()}`
    }
  }
  return null
}

function adjustPartColorForDisplay(hex: string): string {
  const v = colorVividness.value
  const c = new THREE.Color(hex)
  const hsl = { h: 0, s: 0, l: 0 }
  c.getHSL(hsl)
  c.setHSL(hsl.h, hsl.s * (0.55 + 0.45 * v), hsl.l * (0.68 + 0.32 * v))
  return `#${c.getHexString()}`
}

function applyHexToMesh(obj: THREE.Mesh, hex: string): void {
  const col = new THREE.Color(adjustPartColorForDisplay(hex))
  const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
  mats.forEach((m: THREE.Material) => {
    if ('color' in m) {
      const mm = m as THREE.Material & { color: THREE.Color; needsUpdate?: boolean }
      mm.color.copy(col)
      mm.needsUpdate = true
    }
  })
}

function markImportedMeshColors(root: THREE.Object3D) {
  root.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh) || !obj.material) return
    const hex = meshPrimaryHex(obj)
    if (!hex || isNeutralImportedHex(hex)) return
    obj.userData = { ...obj.userData, hasImportedColor: true, partColorHex: hex }
  })
}

/** Применить partColorHex из userData (meta.json / bindPartMeta). */
function applyUserDataPartColors(root: THREE.Object3D): number {
  let painted = 0
  root.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh) || !obj.material) return
    const hex = normalizeHexColor(String(obj.userData?.partColorHex ?? ''))
    if (!hex) return
    applyHexToMesh(obj, hex)
    obj.userData = { ...obj.userData, lockPartColor: true, hasImportedColor: true, partColorHex: hex }
    painted += 1
  })
  return painted
}

/** После загрузки GLB/GLTF: meta, цвета из файла, авто-палитра по сегментам. */
function finalizeModelPartColors(root: THREE.Object3D, partMeta?: PartColorMeta | null): void {
  if (partMeta) {
    const bound = bindPartMetaToMeshes(root, partMeta)
    const painted = applyPartColorsFromMeta(root, partMeta)
    const fromUserData = applyUserDataPartColors(root)
    logger.info(
      'Viewer3D',
      `Цвета meta: привязано ${bound.mapped}/${bound.totalMeshes}, окрашено ${painted}, userData ${fromUserData}`,
    )
  }
  markImportedMeshColors(root)
  const auto = maybeAutoColorizeSegments(root)
  if (auto.enabled) {
    logger.info('Viewer3D', `Авто-раскраска сегментов: ${auto.painted} мешей`)
  }
  applyLargeAssemblyMaterialHints(root)
}

function applyLargeAssemblyMaterialHints(root: THREE.Object3D): void {
  root.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh) || !obj.material) return
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
    mats.forEach((m: THREE.Material) => {
      const mm = m as THREE.MeshPhongMaterial & {
        polygonOffset?: boolean
        polygonOffsetFactor?: number
        polygonOffsetUnits?: number
      }
      if ('polygonOffset' in mm) {
        mm.polygonOffset = true
        mm.polygonOffsetFactor = 1
        mm.polygonOffsetUnits = 1
      }
    })
  })
}

function normalizeHexColor(input: string | undefined): string | null {
  if (!input) return null
  const v = input.trim()
  if (/^#[0-9a-fA-F]{6}$/.test(v)) return v.toLowerCase()
  if (/^#[0-9a-fA-F]{3}$/.test(v)) {
    const r = v[1]
    const g = v[2]
    const b = v[3]
    return `#${r}${r}${g}${g}${b}${b}`.toLowerCase()
  }
  return null
}

function parsePartColorMeta(raw: unknown): PartColorMeta | null {
  if (!raw || typeof raw !== 'object') return null
  const obj = raw as Record<string, unknown>
  const payload =
    obj.metadata && typeof obj.metadata === 'object'
      ? (obj.metadata as Record<string, unknown>)
      : obj

  const partsRaw = Array.isArray(payload.parts) ? payload.parts : []
  const instancesRaw = Array.isArray(payload.instances) ? payload.instances : []
  const meshRaw = Array.isArray(payload.meshBindings) ? payload.meshBindings : []

  const parts: PartColorMetaPart[] = partsRaw
    .map((p) => {
      if (!p || typeof p !== 'object') return null
      const pp = p as Record<string, unknown>
      const partId = String(pp.partId ?? pp.id ?? '').trim()
      if (!partId) return null
      const displayName = String(pp.displayName ?? pp.name ?? '').trim() || undefined
      const color = normalizeHexColor(
        String(pp.defaultColor ?? pp.color ?? pp.colorHex ?? '').trim() || undefined
      )
      return {
        partId,
        displayName,
        name: String(pp.name ?? '').trim() || undefined,
        material: String(pp.material ?? '').trim() || undefined,
        category: String(pp.category ?? pp.kind ?? '').trim() || undefined,
        defaultColor: color ?? undefined,
      }
    })
    .filter((x): x is PartColorMetaPart => !!x)

  const instances: PartColorMetaInstance[] = instancesRaw
    .map((i) => {
      if (!i || typeof i !== 'object') return null
      const ii = i as Record<string, unknown>
      const instanceId = String(ii.instanceId ?? ii.id ?? '').trim()
      const partId = String(ii.partId ?? '').trim()
      if (!instanceId || !partId) return null
      const colorOverride = normalizeHexColor(String(ii.colorOverride ?? '').trim() || undefined) ?? undefined
      return { instanceId, partId, colorOverride }
    })
    .filter((x): x is PartColorMetaInstance => !!x)

  const meshBindings: PartColorMetaBinding[] = meshRaw
    .map((b) => {
      if (!b || typeof b !== 'object') return null
      const bb = b as Record<string, unknown>
      const meshNode = String(bb.meshNode ?? bb.meshNameHint ?? bb.meshName ?? '').trim()
      if (!meshNode) return null
      return {
        meshNode,
        instanceId: String(bb.instanceId ?? '').trim() || undefined,
        partId: String(bb.partId ?? '').trim() || undefined,
      }
    })
    .filter((x): x is PartColorMetaBinding => !!x)

  if (!parts.length && !instances.length && !meshBindings.length) return null
  return { version: typeof payload.version === 'number' ? payload.version : undefined, parts, instances, meshBindings }
}

function bindPartMetaToMeshes(root: THREE.Object3D, meta: PartColorMeta): { mapped: number; totalMeshes: number } {
  const partById = new Map(meta.parts.map((p) => [p.partId, p]))
  const instanceById = new Map(meta.instances.map((i) => [i.instanceId, i]))
  const bindingByNode = new Map(meta.meshBindings.map((b) => [String(b.meshNode).toLowerCase(), b]))

  let mapped = 0
  let totalMeshes = 0
  root.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh)) return
    totalMeshes += 1
    const nodeKey = String(obj.name || obj.parent?.name || '').trim().toLowerCase()
    if (!nodeKey) return
    const binding = bindingByNode.get(nodeKey)
    if (!binding) return
    const instance = binding.instanceId ? instanceById.get(binding.instanceId) : undefined
    const partId = binding.partId ?? instance?.partId
    if (!partId) return
    const part = partById.get(partId)
    const partLabel = String(part?.displayName || part?.name || partId).trim()
    obj.userData = {
      ...obj.userData,
      partId,
      partName: partLabel,
      instanceId: instance?.instanceId ?? null,
      lockPartColor: true,
      partColorHex: normalizeHexColor(instance?.colorOverride) ?? normalizeHexColor(part?.defaultColor) ?? null,
    }
    mapped += 1
  })
  return { mapped, totalMeshes }
}

async function tryLoadKompasMetaAuto(fileName: string): Promise<PartColorMeta | null> {
  const rootDir = String((import.meta as any).env?.VITE_KOMPAS_ROOT_DIR ?? '').trim()
  if (!rootDir) return null
  try {
    const url = `/api/kompas/metadata/auto?root_dir=${encodeURIComponent(rootDir)}`
    const res = await fetchWithTimeout(url, { method: 'GET' }, STEP_METADATA_TIMEOUT_MS)
    if (!res.ok) return null
    const payload = await res.json()
    if (payload?.mode === 'select' && Array.isArray(payload?.assemblies) && payload.assemblies.length > 0) {
      const options = payload.assemblies
        .slice(0, 12)
        .map((a: any, i: number) => `${i + 1}. ${String(a?.name ?? a?.path ?? '')}`)
        .join('\n')
      const answer = window.prompt(`Найдено несколько сборок КОМПАС.\nВыберите номер:\n${options}`, '1')
      const idx = Math.max(1, Number.parseInt(String(answer ?? '1'), 10) || 1) - 1
      const selected = payload.assemblies[Math.min(idx, payload.assemblies.length - 1)]
      const selectedPath = String(selected?.path ?? '').trim()
      if (selectedPath) {
        const one = await fetchWithTimeout(
          `/api/kompas/metadata?assembly_path=${encodeURIComponent(selectedPath)}`,
          { method: 'GET' },
          STEP_METADATA_TIMEOUT_MS
        )
        if (one.ok) {
          const onePayload = await one.json()
          const parsedOne = parsePartColorMeta(onePayload)
          if (parsedOne) return parsedOne
        }
      }
    }
    const parsed = parsePartColorMeta(payload)
    if (!parsed) return null
    logger.info('Viewer3D', `KOMPAS metadata подтянут для ${fileName}`)
    return parsed
  } catch (e) {
    console.warn(`${LOG_PREFIX} kompas metadata auto недоступен:`, e)
    return null
  }
}

async function tryLoadPartMetaByBaseName(baseName: string): Promise<PartColorMeta | null> {
  if (!baseName) return null
  const encoded = encodeURIComponent(baseName)
  const candidates = [
    `/${encoded}.meta.json`,
    `/${encoded}.json`,
    `/meta/${encoded}.meta.json`,
    `/meta/${encoded}.json`,
  ]
  for (const url of candidates) {
    try {
      const res = await fetch(url, { method: 'GET' })
      if (!res.ok) continue
      const parsed = parsePartColorMeta(await res.json())
      if (parsed) {
        logger.info('Viewer3D', `Найден meta.json: ${url}`)
        return parsed
      }
    } catch {
      // ignore
    }
  }
  return null
}

function applyPartColorsFromMeta(root: THREE.Object3D, meta: PartColorMeta): { painted: number; skipped: number } {
  const partById = new Map(meta.parts.map((p) => [p.partId, p]))
  const instanceById = new Map(meta.instances.map((i) => [i.instanceId, i]))
  const bindingByNode = new Map(
    meta.meshBindings.map((b) => [String(b.meshNode).toLowerCase(), b]),
  )
  let painted = 0
  let skipped = 0

  root.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh) || !obj.material) return
    const nodeName = String(obj.name || obj.parent?.name || '').trim().toLowerCase()
    if (!nodeName) {
      skipped += 1
      return
    }
    const binding = bindingByNode.get(nodeName)
    if (!binding) {
      skipped += 1
      return
    }
    const instance = binding.instanceId ? instanceById.get(binding.instanceId) : undefined
    const partId = binding.partId ?? instance?.partId
    const part = partId ? partById.get(partId) : undefined
    const hex = normalizeHexColor(instance?.colorOverride) ?? normalizeHexColor(part?.defaultColor)
    if (!hex) {
      skipped += 1
      return
    }
    applyHexToMesh(obj, hex)
    obj.userData = { ...obj.userData, lockPartColor: true, partColorHex: hex, partId: partId ?? null, instanceId: instance?.instanceId ?? null }
    painted += 1
  })
  return { painted, skipped }
}

const SEGMENT_FALLBACK_PALETTE = [
  '#6a8bc7', '#c7796a', '#6ac79a', '#c7b36a',
  '#8d6ac7', '#6ab9c7', '#c76a9d', '#83c76a',
  '#c78f6a', '#6a72c7', '#c76a6a', '#6ac7c0',
]

/** Свыше — не красим каждый треугольник (типичный fallback STEP без XCAF). */
const AUTO_COLORIZE_MAX_MESHES = 250

const AUTO_COLORIZE_SKIP_NODE_NAMES = new Set(['', 'scene', 'root', 'nodes', 'meshes', 'object3d', 'group'])

function meshSegmentColorKey(obj: THREE.Mesh): string {
  const parts: string[] = []
  let cur: THREE.Object3D | null = obj
  while (cur) {
    const n = String(cur.name || '').trim()
    if (n && !AUTO_COLORIZE_SKIP_NODE_NAMES.has(n.toLowerCase())) parts.unshift(n)
    cur = cur.parent
  }
  if (parts.length) return parts.join('/')
  const parent = obj.parent
  if (parent) {
    const idx = parent.children.indexOf(obj)
    return `mesh:${parent.uuid.slice(0, 8)}:${idx}`
  }
  return obj.uuid
}

function hashStringToIndex(text: string, modulo: number): number {
  let h = 0
  for (let i = 0; i < text.length; i += 1) h = ((h << 5) - h + text.charCodeAt(i)) | 0
  return Math.abs(h) % Math.max(1, modulo)
}

function collectMeshHexColors(root: THREE.Object3D): string[] {
  const colors: string[] = []
  root.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh) || !obj.material) return
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
    mats.forEach((m: THREE.Material) => {
      if ('color' in m) {
        const c = (m as THREE.Material & { color: THREE.Color }).color
        colors.push(`#${c.getHexString()}`)
      }
    })
  })
  return colors
}

function maybeAutoColorizeSegments(root: THREE.Object3D): { painted: number; skipped: number; enabled: boolean } {
  if (!autoColorizeSegments.value || !preservePartColors.value) return { painted: 0, skipped: 0, enabled: false }
  const existing = collectMeshHexColors(root).filter((c) => !isNeutralImportedHex(c))
  const unique = new Set(existing.map((c) => c.toLowerCase()))
  if (unique.size > 3) return { painted: 0, skipped: 0, enabled: false }

  let meshCount = 0
  root.traverse((obj: THREE.Object3D) => {
    if (obj instanceof THREE.Mesh) meshCount += 1
  })
  if (meshCount > AUTO_COLORIZE_MAX_MESHES) {
    logger.info(
      'Viewer3D',
      `Авто-раскраска пропущена: ${meshCount} мешей (лимит ${AUTO_COLORIZE_MAX_MESHES}). Для цветов нужен XCAF STEP или meta.json`,
    )
    return { painted: 0, skipped: meshCount, enabled: false }
  }

  let painted = 0
  let skipped = 0
  root.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh) || !obj.material) return
    if (obj.userData?.lockPartColor || obj.userData?.hasImportedColor) {
      skipped += 1
      return
    }
    const key = meshSegmentColorKey(obj)
    const colorHex = SEGMENT_FALLBACK_PALETTE[hashStringToIndex(key, SEGMENT_FALLBACK_PALETTE.length)]
    applyHexToMesh(obj, colorHex)
    obj.userData = { ...obj.userData, lockPartColor: true, partColorHex: colorHex, autoSegmentColor: true }
    painted += 1
  })
  return { painted, skipped, enabled: painted > 0 }
}

function cloneAsUnlitMaterial(mat: THREE.Material): THREE.Material {
  const src = mat as THREE.Material & { color?: THREE.Color; opacity?: number; transparent?: boolean }
  return new THREE.MeshLambertMaterial({
    color: src.color ? src.color.getHex() : MODEL_COLOR_SINGLE,
    emissive: 0x111111,
    transparent: !!src.transparent,
    opacity: typeof src.opacity === 'number' ? src.opacity : 1,
  })
}

function disposeThreeMaterial(m: THREE.Material | THREE.Material[] | undefined | null) {
  if (!m) return
  if (Array.isArray(m)) m.forEach((mat) => mat.dispose())
  else m.dispose()
}

function disposeObject3DResources(root: THREE.Object3D) {
  root.traverse((obj) => {
    if (obj instanceof THREE.Mesh || obj instanceof THREE.Line || obj instanceof THREE.LineSegments) {
      obj.geometry?.dispose()
      disposeThreeMaterial(obj.material as THREE.Material | THREE.Material[] | undefined)
    }
  })
}

function applySceneLightingForShadingMode() {
  const lit = shadingMode.value === 'lit'
  const preset = lightPreset.value
  const base =
    preset === 'engineering'
      ? { ambient: 0.18, hemi: 0.28, key: 0.92, fillA: 0.11, fillB: 0.08, fillC: 0.06, rimA: 0.2, rimB: 0.14, exposure: 0.96 }
      : { ambient: 0.25, hemi: 0.38, key: 0.82, fillA: 0.24, fillB: 0.18, fillC: 0.13, rimA: 0.16, rimB: 0.12, exposure: 1.12 }
  const tone = 0.78 + (tintBrightness.value - TINT_BRIGHTNESS_MIN) / (TINT_BRIGHTNESS_MAX - TINT_BRIGHTNESS_MIN) * 0.62
  const toneSafe = Math.min(1.55, Math.max(0.7, tone))
  const unl = lit ? 1 : 1.22
  const fillMul = extraFillLightsEnabled.value ? 1 : 0
  const rimMul = extraRimLightsEnabled.value ? 1 : 0
  if (ambientLight) ambientLight.intensity = base.ambient * unl * toneSafe
  if (hemiLight) hemiLight.intensity = base.hemi * unl * toneSafe
  if (keyLight) keyLight.intensity = base.key * (lit ? 1 : 0.9) * toneSafe
  if (fillLightA) fillLightA.intensity = base.fillA * unl * toneSafe * fillMul
  if (fillLightB) fillLightB.intensity = base.fillB * unl * toneSafe * fillMul
  if (fillLightC) fillLightC.intensity = base.fillC * unl * toneSafe * fillMul
  if (rimLightA) rimLightA.intensity = base.rimA * (lit ? 1 : 0.9) * toneSafe * rimMul
  if (rimLightB) rimLightB.intensity = base.rimB * (lit ? 1 : 0.9) * toneSafe * rimMul
  if (renderer) renderer.toneMappingExposure = base.exposure * (0.88 + toneSafe * 0.3)
  if (renderer) renderer.shadowMap.enabled = false
}

function setMeshGroupShadowState(enabled: boolean) {
  if (!meshGroup) return
  meshGroup.traverse((obj: THREE.Object3D) => {
    if (obj instanceof THREE.Mesh) {
      obj.castShadow = enabled
      obj.receiveShadow = enabled
    }
  })
}

function applyShadingMode() {
  if (!meshGroup) return
  restoreWireframeFaceGhost()
  meshGroup.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh) || !obj.material) return
    if (shadingMode.value === 'unlit') {
      if (!originalMaterials.has(obj)) originalMaterials.set(obj, obj.material)
      const source = originalMaterials.get(obj) ?? obj.material
      const prev = obj.material
      obj.material = Array.isArray(source)
        ? source.map((m) => cloneAsUnlitMaterial(m))
        : cloneAsUnlitMaterial(source)
      if (prev !== source) disposeThreeMaterial(prev)
      return
    }
    const original = originalMaterials.get(obj)
    if (original) {
      const prev = obj.material
      if (prev !== original) disposeThreeMaterial(prev)
      obj.material = original
      originalMaterials.delete(obj)
    }
  })
  applyModelTint()
  applySceneLightingForShadingMode()
  setMeshGroupShadowState(false)
  syncWireframeEdges()
  applyUserOpacityToMeshGroup()
  if (selectedPartRowKeys.value.size > 0) {
    applySelectionVisualsAndFocus()
  }
}

function onShadingModeChange(ev: Event) {
  const value = (ev.target as HTMLSelectElement).value
  shadingMode.value = value === 'unlit' ? 'unlit' : 'lit'
  applyShadingMode()
}

function onLightPresetChange(ev: Event) {
  const value = (ev.target as HTMLSelectElement).value
  lightPreset.value = value === 'soft' ? 'soft' : 'engineering'
  applyShadingMode()
}

function onPreservePartColorsChange() {
  applyShadingMode()
}

function onOverlayEnabledChange() {
  updateOverlayVisuals()
}

function onOverlayOpacityInput(ev: Event) {
  const val = Number((ev.target as HTMLInputElement).value)
  if (!Number.isFinite(val)) return
  overlayOpacity.value = clampOverlayOpacity(val)
  updateOverlayVisuals()
}

function clampExplode(v: number): number {
  return Math.max(EXPLODE_MIN, Math.min(EXPLODE_MAX, v))
}

function collectPartGroupsFromTree(nodes: ComponentTreeNode[]): string[][] {
  const groups: string[][] = []
  const walk = (list: ComponentTreeNode[]) => {
    for (const n of list) {
      if (n.targetIds.length > 0) groups.push([...n.targetIds])
      if (n.children.length) walk(n.children)
    }
  }
  walk(nodes)
  return groups
}

/**
 * Разнесение: ползунок 0…100 = % от макс. стороны габарита модели (мм).
 * Профиль габаритов фиксируется при импорте (после нормализации в мм).
 */
interface ModelExplodeProfile {
  sizeMm: { x: number; y: number; z: number }
  diagonalMm: number
  maxAxisMm: number
  avgPartOffsetMm: number
  maxPartOffsetMm: number
  partGroupCount: number
  unitsSource: 'mm-native' | 'scaled-from-meters'
}

function getModelExplodeProfile(wrapper: THREE.Group): ModelExplodeProfile | null {
  return (wrapper.userData.explodeProfile as ModelExplodeProfile | undefined) ?? null
}

function getWrapperMaxAxisMm(wrapper: THREE.Group): number {
  const profile = getModelExplodeProfile(wrapper)
  if (profile && profile.maxAxisMm > 0) return profile.maxAxisMm
  wrapper.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(wrapper)
  if (box.isEmpty()) return 1000
  const size = box.getSize(new THREE.Vector3())
  return Math.max(size.x, size.y, size.z)
}

/** Вызывается сразу после ensureModelUnitsMillimeters при импорте. */
function updateModelExplodeProfileOnImport(wrapper: THREE.Group, modelName?: string) {
  wrapper.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(wrapper)
  if (box.isEmpty()) return
  const size = box.getSize(new THREE.Vector3())
  const diagonalMm = size.length()
  const maxAxisMm = Math.max(size.x, size.y, size.z)
  const scaledFromMeters = wrapper.userData.unitScaleFromMeters === METERS_TO_MM_SCALE
  const profile: ModelExplodeProfile = {
    sizeMm: { x: size.x, y: size.y, z: size.z },
    diagonalMm,
    maxAxisMm,
    avgPartOffsetMm: 0,
    maxPartOffsetMm: 0,
    partGroupCount: 0,
    unitsSource: scaledFromMeters ? 'scaled-from-meters' : 'mm-native',
  }
  wrapper.userData.explodeProfile = profile
  const label = modelName ?? String(wrapper.userData?.modelId ?? 'модель')
  logger.info(
    'Viewer3D',
    `Разнесение: «${label}» ${size.x.toFixed(0)}×${size.y.toFixed(0)}×${size.z.toFixed(0)} мм, ` +
      `макс. сторона ${maxAxisMm.toFixed(0)} мм → 1% = ${(maxAxisMm / 100).toFixed(1)} мм, 100% = ${maxAxisMm.toFixed(0)} мм, ` +
      `ед.: ${profile.unitsSource === 'scaled-from-meters' ? 'м→мм' : 'мм'}`,
  )
}

function partGroupCentroidWorld(meshUuids: string[], meshByUuid: Map<string, THREE.Mesh>): THREE.Vector3 | null {
  const centroid = new THREE.Vector3()
  let count = 0
  for (const id of meshUuids) {
    const mesh = meshByUuid.get(id)
    if (!mesh) continue
    const box = new THREE.Box3().setFromObject(mesh)
    centroid.add(box.getCenter(new THREE.Vector3()))
    count += 1
  }
  if (count === 0) return null
  return centroid.multiplyScalar(1 / count)
}

function partGroupBBoxVolume(meshUuids: string[], meshByUuid: Map<string, THREE.Mesh>): number {
  const box = new THREE.Box3()
  for (const id of meshUuids) {
    const mesh = meshByUuid.get(id)
    if (!mesh) continue
    box.expandByObject(mesh)
  }
  if (box.isEmpty()) return 0
  const s = box.getSize(new THREE.Vector3())
  return s.x * s.y * s.z
}

function partGroupMaxExtent(meshUuids: string[], meshByUuid: Map<string, THREE.Mesh>): number {
  const box = new THREE.Box3()
  for (const id of meshUuids) {
    const mesh = meshByUuid.get(id)
    if (!mesh) continue
    box.expandByObject(mesh)
  }
  if (box.isEmpty()) return 0
  const s = box.getSize(new THREE.Vector3())
  return Math.max(s.x, s.y, s.z)
}

interface ExplodePartGroupLayout {
  ids: string[]
  centroid: THREE.Vector3
  isAnchor: boolean
  radialDir: THREE.Vector3
  radialDist: number
  pairDir: THREE.Vector3
  extent: number
}

function partGroupKey(ids: string[]): string {
  return [...ids].sort().join('|')
}

function pickLargestPartGroup(partGroups: string[][], meshByUuid: Map<string, THREE.Mesh>): string[] {
  let best: string[] = []
  let bestVol = -1
  for (const ids of partGroups) {
    const vol = partGroupBBoxVolume(ids, meshByUuid)
    if (vol > bestVol) {
      bestVol = vol
      best = ids
    }
  }
  return best
}

function ensurePartGroupsCoverAllMeshes(partGroups: string[][], meshByUuid: Map<string, THREE.Mesh>): string[][] {
  const groups = partGroups.map((g) => [...g])
  const assigned = new Set<string>()
  for (const ids of groups) ids.forEach((id) => assigned.add(id))
  meshByUuid.forEach((_mesh, uuid) => {
    if (!assigned.has(uuid)) groups.push([uuid])
  })
  return groups
}

/** Доли хода: от якоря + отталкивание соседних деталей друг от друга. */
const EXPLODE_RADIAL_TRAVEL_BLEND = 0.35
const EXPLODE_PAIR_TRAVEL_BLEND = 0.9

/**
 * Якорь — крупнейшая деталь (не двигается). Остальные: от якоря (дальше — сильнее) + разъезд с соседями.
 */
function buildExplodeOffsetsFromLargestAnchor(
  partGroups: string[][],
  meshByUuid: Map<string, THREE.Mesh>,
  wrapper: THREE.Group,
): THREE.Vector3 | null {
  if (partGroups.length === 0) return null
  const anchorIds = pickLargestPartGroup(partGroups, meshByUuid)
  const anchorKey = partGroupKey(anchorIds)
  const anchorCenter = partGroupCentroidWorld(anchorIds, meshByUuid)
  if (!anchorCenter) return null

  const layouts: ExplodePartGroupLayout[] = []
  for (const ids of partGroups) {
    const cen = partGroupCentroidWorld(ids, meshByUuid)
    if (!cen) continue
    const isAnchor = partGroupKey(ids) === anchorKey
    const radial = cen.clone().sub(anchorCenter)
    const radialDist = radial.length()
    const radialDir = radialDist > 1e-6 ? radial.clone().normalize() : new THREE.Vector3(0, 0, 1)
    layouts.push({
      ids,
      centroid: cen,
      isAnchor,
      radialDir,
      radialDist,
      pairDir: new THREE.Vector3(),
      extent: partGroupMaxExtent(ids, meshByUuid),
    })
  }

  const movable = layouts.filter((g) => !g.isAnchor)
  const maxRadialDist = movable.reduce((m, g) => Math.max(m, g.radialDist), 1e-6)
  const refGap = getWrapperMaxAxisMm(wrapper) * 0.04

  for (let i = 0; i < movable.length; i++) {
    for (let j = i + 1; j < movable.length; j++) {
      const a = movable[i]
      const b = movable[j]
      const diff = a.centroid.clone().sub(b.centroid)
      const dist = diff.length()
      if (dist < 1e-6) continue
      const desired = (a.extent + b.extent) * 0.45 + refGap
      if (dist >= desired * 1.35) continue
      const strength = Math.min(1.5, (desired - dist) / Math.max(desired, 1e-6) + 0.15)
      const push = diff.clone().normalize().multiplyScalar(strength)
      a.pairDir.add(push)
      b.pairDir.add(push.clone().negate())
    }
  }

  wrapper.userData.explodeMaxRadialDist = maxRadialDist

  for (const g of layouts) {
    for (const id of g.ids) {
      const mesh = meshByUuid.get(id)
      if (!mesh) continue
      if (!mesh.userData.explodeBasePos) mesh.userData.explodeBasePos = mesh.position.clone()
      mesh.userData.explodeFixed = g.isAnchor
      mesh.userData.explodeRadialDir = g.radialDir.clone()
      mesh.userData.explodeRadialDist = g.radialDist
      mesh.userData.explodePairDir = g.pairDir.clone()
      delete mesh.userData.explodeOffsetWorld
      delete mesh.userData.explodeOffset
      delete mesh.userData.explodeDir
    }
  }
  return anchorCenter.clone()
}

function refineExplodeProfileFromPartLayout(
  wrapper: THREE.Group,
  anchorCenterWorld: THREE.Vector3,
  meshByUuid: Map<string, THREE.Mesh>,
  partGroups: string[][],
) {
  const profile = getModelExplodeProfile(wrapper)
  if (!profile) return

  const anchorKey = partGroupKey(pickLargestPartGroup(partGroups, meshByUuid))
  const offsets: number[] = []
  for (const ids of partGroups) {
    if (partGroupKey(ids) === anchorKey) continue
    const cen = partGroupCentroidWorld(ids, meshByUuid)
    if (!cen) continue
    offsets.push(cen.distanceTo(anchorCenterWorld))
  }

  profile.partGroupCount = partGroups.length
  if (offsets.length > 0) {
    profile.avgPartOffsetMm = offsets.reduce((a, b) => a + b, 0) / offsets.length
    profile.maxPartOffsetMm = Math.max(...offsets)
  }

  logger.info(
    'Viewer3D',
    `Разнесение: якорь — крупнейшая деталь (${pickLargestPartGroup(partGroups, meshByUuid).length} меш.), ` +
      `ещё ${Math.max(0, partGroups.length - 1)} групп (от якоря + друг от друга), ход ≈ ${profile.maxAxisMm.toFixed(0)} мм × %`,
  )
}

function getWrapperBBoxDiagonalMm(wrapper: THREE.Group): number {
  const profile = getModelExplodeProfile(wrapper)
  if (profile) return profile.diagonalMm
  const box = new THREE.Box3().setFromObject(wrapper)
  if (box.isEmpty()) return 1000
  return box.getSize(new THREE.Vector3()).length()
}

/** Ход разнесения (мм): amount = процент от макс. стороны габарита модели. */
function explodeTravelMmForWrapper(wrapper: THREE.Group, amount: number): number {
  if (amount <= 0) return 0
  const maxAxisMm = getWrapperMaxAxisMm(wrapper)
  return (amount / 100) * maxAxisMm
}

const explodeTravelHint = computed(() => {
  const pct = explodeAmount.value
  if (pct <= 0) return null
  let travelMm = 0
  modelGroupsById.forEach((wrapper) => {
    travelMm = Math.max(travelMm, explodeTravelMmForWrapper(wrapper, pct))
  })
  if (travelMm <= 0) return null
  const mm = Math.round(travelMm * (1 + EXPLODE_PAIR_TRAVEL_BLEND))
  return { pct, mm }
})

function resetMeshesToExplodeBase(wrapper: THREE.Group) {
  wrapper.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh)) return
    const base = obj.userData.explodeBasePos as THREE.Vector3 | undefined
    if (base) obj.position.copy(base)
  })
  wrapper.updateMatrixWorld(true)
}

function ensureExplodeCacheForModel(wrapper: THREE.Group, rebuildOffsets = false) {
  if (!rebuildOffsets && wrapper.userData.explodeCacheReady) return
  resetMeshesToExplodeBase(wrapper)
  const meshByUuid = new Map<string, THREE.Mesh>()
  wrapper.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh)) return
    delete obj.userData.explodeFixed
    delete obj.userData.explodeOffsetWorld
    delete obj.userData.explodeRadialDir
    delete obj.userData.explodeRadialDist
    delete obj.userData.explodePairDir
    meshByUuid.set(obj.uuid, obj)
  })
  delete wrapper.userData.explodeMaxRadialDist
  const modelId = String(wrapper.userData?.modelId ?? '')
  const tree = modelId ? componentTreeByModel.value[modelId] : undefined
  let partGroups = tree?.length ? collectPartGroupsFromTree(tree) : []
  partGroups = ensurePartGroupsCoverAllMeshes(partGroups, meshByUuid)
  const anchorCenter = buildExplodeOffsetsFromLargestAnchor(partGroups, meshByUuid, wrapper)
  if (anchorCenter) refineExplodeProfileFromPartLayout(wrapper, anchorCenter, meshByUuid, partGroups)
  wrapper.userData.explodeCacheReady = true
}

function resetExplodeAmount() {
  explodeAmount.value = 0
  applyExplodeToAllModels()
}

function applyExplodePositionsOnly(wrapper: THREE.Group, amount: number) {
  if (!wrapper.userData.explodeCacheReady) {
    ensureExplodeCacheForModel(wrapper, true)
  }
  const travelMm = explodeTravelMmForWrapper(wrapper, amount)
  const maxRadialDist = (wrapper.userData.explodeMaxRadialDist as number | undefined) ?? 1
  const baseWorld = new THREE.Vector3()
  const targetWorld = new THREE.Vector3()
  const moveWorld = new THREE.Vector3()
  wrapper.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh)) return
    const mesh = obj
    const base = mesh.userData.explodeBasePos as THREE.Vector3 | undefined
    if (!base) return
    const parent = mesh.parent
    mesh.position.copy(base)
    if (mesh.userData.explodeFixed || travelMm <= 0 || !parent) {
      mesh.updateMatrix()
      return
    }
    const radialDir = mesh.userData.explodeRadialDir as THREE.Vector3 | undefined
    const radialDist = (mesh.userData.explodeRadialDist as number | undefined) ?? 0
    const pairDir = mesh.userData.explodePairDir as THREE.Vector3 | undefined
    if (!radialDir && (!pairDir || pairDir.lengthSq() < 1e-12)) {
      mesh.updateMatrix()
      return
    }
    mesh.updateMatrixWorld(true)
    mesh.getWorldPosition(baseWorld)
    moveWorld.set(0, 0, 0)
    if (radialDir && radialDir.lengthSq() > 1e-12) {
      const radialT = maxRadialDist > 1e-6 ? radialDist / maxRadialDist : 1
      const radialScale = EXPLODE_RADIAL_TRAVEL_BLEND + (1 - EXPLODE_RADIAL_TRAVEL_BLEND) * radialT
      moveWorld.add(radialDir.clone().multiplyScalar(travelMm * radialScale))
    }
    if (pairDir && pairDir.lengthSq() > 1e-12) {
      moveWorld.add(pairDir.clone().normalize().multiplyScalar(travelMm * EXPLODE_PAIR_TRAVEL_BLEND))
    }
    if (moveWorld.lengthSq() < 1e-12) {
      mesh.updateMatrix()
      return
    }
    targetWorld.copy(baseWorld).add(moveWorld)
    parent.worldToLocal(targetWorld)
    mesh.position.copy(targetWorld)
    mesh.updateMatrix()
  })
  wrapper.updateMatrixWorld(true)
  if (wireframeModeRef.value) syncWireframeEdges(wrapper)
}

function applyExplodeForModel(wrapper: THREE.Group, amount: number) {
  applyExplodePositionsOnly(wrapper, amount)
}

function applyExplodeToAllModels() {
  modelGroupsById.forEach((wrapper) => {
    applyExplodePositionsOnly(wrapper, explodeAmount.value)
  })
  scheduleSceneMetricsRecalc()
  refreshActiveMeasurementAnchors()
  if (measureModeRef.value && measurementPoints.length) updateMeasurementGraphics()
  rebuildSavedMeasurementsVisuals()
}

function onExplodeInput(ev: Event) {
  const v = Number((ev.target as HTMLInputElement).value)
  if (!Number.isFinite(v)) return
  explodeAmount.value = clampExplode(v)
  applyExplodeToAllModels()
}

watch(explodeAmount, (v) => {
  if (v > EXPLODE_MAX) explodeAmount.value = EXPLODE_MAX
})

function clampOverlayOpacity(v: number): number {
  return Math.max(OVERLAY_OPACITY_MIN, Math.min(OVERLAY_OPACITY_MAX, v))
}

function extractMeshColorHex(mesh: THREE.Mesh): string {
  const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
  const first = mats.find((m) => 'color' in m) as (THREE.Material & { color?: THREE.Color }) | undefined
  return first?.color ? `#${first.color.getHexString()}` : '#6a8bc7'
}

function createOverlayMaterial(colorHex: string): THREE.MeshBasicMaterial {
  return new THREE.MeshBasicMaterial({
    color: new THREE.Color(colorHex),
    transparent: true,
    opacity: overlayOpacity.value,
    depthTest: true,
    depthWrite: false,
    polygonOffset: true,
    polygonOffsetFactor: -3,
    polygonOffsetUnits: -3,
    side: THREE.DoubleSide,
    toneMapped: false,
  })
}

const OVERLAY_MONO_PALETTE = [
  '#7fa3cc', '#789ec7', '#7398c1', '#6d93bc',
  '#678eb6', '#6189b1', '#5c84ab', '#567fa6',
]

function overlayMonochromeColorForMesh(obj: THREE.Mesh): string {
  const key = String(obj.parent?.name || obj.name || obj.uuid)
  const idx = hashStringToIndex(key, OVERLAY_MONO_PALETTE.length)
  return OVERLAY_MONO_PALETTE[idx]
}

function updateOverlayVisuals() {
  overlayGroup.visible = overlayEnabled.value
  overlayGroup.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh) || !obj.material) return
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
    mats.forEach((m: THREE.Material) => {
      const mm = m as THREE.Material & { opacity?: number; transparent?: boolean; depthWrite?: boolean; needsUpdate?: boolean }
      if ('opacity' in mm) mm.opacity = overlayOpacity.value
      if ('transparent' in mm) mm.transparent = true
      if ('depthWrite' in mm) mm.depthWrite = false
      mm.needsUpdate = true
    })
  })
}

function buildOverlayForModel(modelId: string, sourceWrapper: THREE.Group): THREE.Group {
  const overlayWrapper = new THREE.Group()
  overlayWrapper.userData = { modelId, overlayWrapper: true }
  sourceWrapper.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh) || !obj.geometry || !obj.material) return
    const mesh = new THREE.Mesh(obj.geometry, createOverlayMaterial(overlayMonochromeColorForMesh(obj)))
    mesh.matrixAutoUpdate = false
    mesh.userData = { overlayMesh: true, sourceUuid: obj.uuid }
    // Не участвует в хиттестах/измерениях.
    mesh.raycast = () => {}
    const local = sourceWrapper.worldToLocal(obj.getWorldPosition(new THREE.Vector3()))
    const worldQuat = obj.getWorldQuaternion(new THREE.Quaternion())
    const localQuat = sourceWrapper.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(worldQuat)
    const worldScale = obj.getWorldScale(new THREE.Vector3())
    const sourceScale = sourceWrapper.getWorldScale(new THREE.Vector3())
    mesh.position.copy(local)
    mesh.quaternion.copy(localQuat)
    mesh.scale.set(
      sourceScale.x !== 0 ? worldScale.x / sourceScale.x : worldScale.x,
      sourceScale.y !== 0 ? worldScale.y / sourceScale.y : worldScale.y,
      sourceScale.z !== 0 ? worldScale.z / sourceScale.z : worldScale.z,
    )
    mesh.updateMatrix()
    overlayWrapper.add(mesh)
  })
  overlayWrapper.position.copy(sourceWrapper.position)
  overlayWrapper.quaternion.copy(sourceWrapper.quaternion)
  overlayWrapper.scale.copy(sourceWrapper.scale)
  overlayWrapper.updateMatrixWorld(true)
  return overlayWrapper
}

function syncOverlayTransforms() {
  overlaySourceByModelId.forEach((source, modelId) => {
    const overlay = overlayGroupByModelId.get(modelId)
    if (!overlay) return
    overlay.position.copy(source.position)
    overlay.quaternion.copy(source.quaternion)
    overlay.scale.copy(source.scale)
  })
}

function syncOverlayVisibilityForModel(modelId: string) {
  const source = overlaySourceByModelId.get(modelId)
  const overlay = overlayGroupByModelId.get(modelId)
  if (!source || !overlay) return
  const visByUuid = new Map<string, boolean>()
  source.traverse((obj: THREE.Object3D) => {
    visByUuid.set(obj.uuid, obj.visible)
  })
  overlay.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh)) return
    const sourceUuid = String(obj.userData?.sourceUuid ?? '')
    if (!sourceUuid) return
    const v = visByUuid.get(sourceUuid)
    if (typeof v === 'boolean') obj.visible = v
  })
}

function componentKey(modelId: string, objectId: string): string {
  return `${modelId}:${objectId}`
}

function setHiddenOutlineForObject(modelId: string, obj: THREE.Object3D, hidden: boolean) {
  const key = componentKey(modelId, obj.uuid)
  const existing = hiddenOutlineByComponentId.get(key)
  if (!hidden) {
    if (existing) {
      hiddenOutlineGroup.remove(existing)
      existing.geometry.dispose()
      ;(existing.material as THREE.Material).dispose()
      hiddenOutlineByComponentId.delete(key)
    }
    return
  }
  if (existing) return
  const box = new THREE.Box3().setFromObject(obj)
  if (box.isEmpty()) return
  const helper = new THREE.Box3Helper(box, 0x35d35a)
  helper.userData = { hiddenComponentKey: key, modelId, objectId: obj.uuid }
  hiddenOutlineByComponentId.set(key, helper)
  hiddenOutlineGroup.add(helper)
}

/** Убирает контуры скрытых деталей (глаз в дереве — полное скрытие без bbox). */
function clearHiddenOutlinesForModel(modelId: string) {
  const group = modelGroupsById.get(modelId)
  if (!group) return
  group.traverse((obj: THREE.Object3D) => {
    if (obj === group || !(obj instanceof THREE.Mesh)) return
    setHiddenOutlineForObject(modelId, obj, false)
  })
}

function ensureOverlayForModel(_modelId: string, _sourceWrapper: THREE.Group) {
  /* оверлей отключён — меньше геометрии в GPU */
}

function removeOverlayForModel(modelId: string, dispose = false) {
  const overlay = overlayGroupByModelId.get(modelId)
  if (!overlay) return
  overlayGroup.remove(overlay)
  if (dispose) {
    overlay.traverse((obj: THREE.Object3D) => {
      if (obj instanceof THREE.Mesh && obj.material) {
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
        mats.forEach((m: THREE.Material) => m.dispose())
      }
    })
    overlayGroupByModelId.delete(modelId)
    overlaySourceByModelId.delete(modelId)
  }
}

function onAutoNavLimitsChange() {
  if (!autoNavLimitsEnabled.value || !meshGroup || meshGroup.children.length === 0) return
  applyAutoNavigationLimits()
}

function getAssemblyModelBox(modelId: string): THREE.Box3 | null {
  const group = modelGroupsById.get(modelId)
  if (!group || !group.visible) return null
  const box = new THREE.Box3().setFromObject(group)
  return box.isEmpty() ? null : box
}

function getAxisCenter(box: THREE.Box3, axis: AssemblyAxis): number {
  return axis === 'x' ? (box.min.x + box.max.x) * 0.5 : axis === 'y' ? (box.min.y + box.max.y) * 0.5 : (box.min.z + box.max.z) * 0.5
}

function getAxisSideValue(box: THREE.Box3, axis: AssemblyAxis, side: AssemblyPlaneSide): number {
  if (axis === 'x') return side === 'min' ? box.min.x : box.max.x
  if (axis === 'y') return side === 'min' ? box.min.y : box.max.y
  return side === 'min' ? box.min.z : box.max.z
}

function moveGroupAlongAxis(group: THREE.Group, axis: AssemblyAxis, delta: number) {
  if (axis === 'x') group.position.x += delta
  else if (axis === 'y') group.position.y += delta
  else group.position.z += delta
}

function newAssemblyMateId(): string {
  return `mate_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`
}

function persistAssemblyPlane(p: AssemblyPlaneSelection): StoredAssemblyPlane {
  return {
    modelId: p.modelId,
    localPoint: { x: p.localPoint.x, y: p.localPoint.y, z: p.localPoint.z },
    normal: { x: p.normal.x, y: p.normal.y, z: p.normal.z },
  }
}

function storedToAssemblyPlane(sp: StoredAssemblyPlane): AssemblyPlaneSelection {
  return {
    modelId: sp.modelId,
    localPoint: new THREE.Vector3(sp.localPoint.x, sp.localPoint.y, sp.localPoint.z),
    point: new THREE.Vector3(),
    normal: new THREE.Vector3(sp.normal.x, sp.normal.y, sp.normal.z),
  }
}

/** Сдвиг источника вдоль нормали опорной грани: после сдвига (pwSrc′ − pwDst)·n_op = distanceMm (зазор между параллельными плоскостями в мм). */
function matePlaneDeltaVector(
  sourceGroup: THREE.Group,
  targetGroup: THREE.Group,
  src: AssemblyPlaneSelection,
  dst: AssemblyPlaneSelection,
  distanceMm: number,
): THREE.Vector3 | null {
  const nd = dst.normal.clone().normalize()
  const ns = src.normal.clone().normalize()
  if (Math.abs(nd.dot(ns)) < 0.85) return null
  const pwSrc = sourceGroup.localToWorld(src.localPoint.clone())
  const pwDst = targetGroup.localToWorld(dst.localPoint.clone())
  const sep = pwSrc.clone().sub(pwDst).dot(nd)
  return nd.clone().multiplyScalar(distanceMm - sep)
}

function worldCoordPlaneDefinition(id: WorldCoordPlaneId): { normal: THREE.Vector3; label: string } {
  switch (id) {
    case 'xy_neg':
      return { normal: new THREE.Vector3(0, 0, -1), label: 'XY (−Z)' }
    case 'xz_pos':
      return { normal: new THREE.Vector3(0, 1, 0), label: 'XZ (+Y)' }
    case 'xz_neg':
      return { normal: new THREE.Vector3(0, -1, 0), label: 'XZ (−Y)' }
    case 'yz_pos':
      return { normal: new THREE.Vector3(1, 0, 0), label: 'YZ (+X)' }
    case 'yz_neg':
      return { normal: new THREE.Vector3(-1, 0, 0), label: 'YZ (−X)' }
    default:
      return { normal: new THREE.Vector3(0, 0, 1), label: 'XY (+Z)' }
  }
}

const WORLD_COORD_PLANE_ORIGIN = new THREE.Vector3(0, 0, 0)

function rotateGroupAroundLocalPivot(group: THREE.Group, pivotLocal: THREE.Vector3, q: THREE.Quaternion) {
  group.position.sub(pivotLocal)
  group.position.applyQuaternion(q)
  group.position.add(pivotLocal)
  group.quaternion.premultiply(q)
  group.updateMatrixWorld(true)
}

function worldNormalToModelLocal(group: THREE.Group, normalWorld: THREE.Vector3): THREE.Vector3 {
  const inv = new THREE.Matrix3().getNormalMatrix(group.matrixWorld)
  return normalWorld.clone().applyMatrix3(inv).normalize()
}

function updatePlaneSelectionNormalToWorld(
  pick: AssemblyPlaneSelection,
  group: THREE.Group,
  normalWorld: THREE.Vector3,
) {
  pick.normal.copy(worldNormalToModelLocal(group, normalWorld))
}

/** Повернуть модель: нормаль грани → целевая (кратчайший поворот, не только при уже параллельных). */
function alignSourcePlaneNormalToWorld(
  sourceGroup: THREE.Group,
  src: AssemblyPlaneSelection,
  targetNormalWorld: THREE.Vector3,
  preferFlip = false,
): void {
  const ns = src.normal.clone().transformDirection(sourceGroup.matrixWorld).normalize()
  let nt = targetNormalWorld.clone().normalize()
  if (preferFlip) nt.negate()
  else if (ns.dot(nt) < 0) nt.negate()
  const q = new THREE.Quaternion()
  const d = ns.dot(nt)
  if (d < -0.999) {
    const aux = Math.abs(ns.x) < 0.85 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 1, 0)
    const ax = new THREE.Vector3().crossVectors(ns, aux).normalize()
    q.setFromAxisAngle(ax, Math.PI)
  } else {
    q.setFromUnitVectors(ns, nt)
  }
  rotateGroupAroundLocalPivot(sourceGroup, src.localPoint, q)
  updatePlaneSelectionNormalToWorld(src, sourceGroup, nt)
}

function matePlaneToWorldDeltaVector(
  sourceGroup: THREE.Group,
  src: AssemblyPlaneSelection,
  worldNormal: THREE.Vector3,
  distanceMm: number,
): THREE.Vector3 | null {
  const nd = worldNormal.clone().normalize()
  const ns = src.normal.clone().transformDirection(sourceGroup.matrixWorld).normalize()
  if (Math.abs(nd.dot(ns)) < 0.5) return null
  const pwSrc = sourceGroup.localToWorld(src.localPoint.clone())
  const sep = pwSrc.clone().sub(WORLD_COORD_PLANE_ORIGIN).dot(nd)
  return nd.clone().multiplyScalar(distanceMm - sep)
}

function applyCoordPlaneMateToGroup(
  sourceGroup: THREE.Group,
  src: AssemblyPlaneSelection,
  worldPlaneId: WorldCoordPlaneId,
  distanceMm: number,
  flipNormal: boolean,
): { ok: boolean; message: string; deltaLen: number } {
  if (src.surfaceKind === 'cylinder') {
    return {
      ok: false,
      message:
        'Выбрана цилиндрическая поверхность. Для координат используйте плоскую грань; сопряжение осей цилиндров — отдельный режим (скоро).',
      deltaLen: 0,
    }
  }
  if (src.surfaceKind && src.surfaceKind !== 'plane') {
    return { ok: false, message: 'Нужна плоская грань модели (не кривая поверхность).', deltaLen: 0 }
  }
  let { normal: worldN, label } = worldCoordPlaneDefinition(worldPlaneId)
  if (flipNormal) worldN = worldN.clone().multiplyScalar(-1)
  alignSourcePlaneNormalToWorld(sourceGroup, src, worldN, flipNormal)
  const dv = matePlaneToWorldDeltaVector(sourceGroup, src, worldN, distanceMm)
  if (!dv) {
    return { ok: false, message: 'Не удалось совместить плоскости после поворота.', deltaLen: 0 }
  }
  sourceGroup.position.add(dv)
  return {
    ok: true,
    message: `Совмещено с ${label}: поворот + сдвиг ${dv.length().toFixed(2)} мм`,
    deltaLen: dv.length(),
  }
}

function solveCoordStoredMate(sourceGroup: THREE.Group, m: Extract<StoredAssemblyMate, { type: 'coord' }>) {
  const src = storedToAssemblyPlane(m.sourcePlane)
  applyCoordPlaneMateToGroup(sourceGroup, src, m.worldPlane, m.distanceMm, m.flipNormal)
}

/** Симметрия по ширине: середина между двумя плоскостями детали совпадает с серединой между двумя плоскостями базы. */
function mateSymmetricDeltaVector(
  sourceGroup: THREE.Group,
  targetGroup: THREE.Group,
  base1: AssemblyPlaneSelection,
  base2: AssemblyPlaneSelection,
  part1: AssemblyPlaneSelection,
  part2: AssemblyPlaneSelection,
): THREE.Vector3 | null {
  const n1 = base1.normal.clone().normalize()
  const n2 = base2.normal.clone().normalize()
  if (Math.abs(n1.dot(n2)) < 0.85) return null
  const n = n1.clone()
  if (n.dot(n2) < 0) n.negate()
  const p1n = part1.normal.clone().normalize()
  const p2n = part2.normal.clone().normalize()
  if (Math.abs(p1n.dot(p2n)) < 0.85) return null
  if (Math.abs(p1n.dot(n)) < 0.45 || Math.abs(p2n.dot(n)) < 0.45) return null
  const B1w = targetGroup.localToWorld(base1.localPoint.clone())
  const B2w = targetGroup.localToWorld(base2.localPoint.clone())
  const P1w = sourceGroup.localToWorld(part1.localPoint.clone())
  const P2w = sourceGroup.localToWorld(part2.localPoint.clone())
  const d = (v: THREE.Vector3) => n.dot(v)
  const midBase = (d(B1w) + d(B2w)) * 0.5
  const midPart = (d(P1w) + d(P2w)) * 0.5
  return n.clone().multiplyScalar(midBase - midPart)
}

function refreshAfterAssemblyMove() {
  if (!meshGroup?.children.length) return
  meshGroup.updateMatrixWorld(true)
  refreshSelectedMeasurementAfterTransform()
  rebuildSavedMeasurementsVisuals()
  const box = new THREE.Box3().setFromObject(meshGroup)
  updateGroundGrid(box)
  updateSceneLighting(box)
  scheduleSceneMetricsRecalc()
}

function solveStoredMate(m: StoredAssemblyMate): void {
  if (m.type === 'coord') {
    const sourceGroup = modelGroupsById.get(m.sourceId)
    if (!sourceGroup || !sourceGroup.visible) return
    solveCoordStoredMate(sourceGroup, m)
    return
  }
  const sourceGroup = modelGroupsById.get(m.sourceId)
  const targetGroup = modelGroupsById.get(m.targetId)
  if (!sourceGroup || !targetGroup || !sourceGroup.visible || !targetGroup.visible) return
  if (m.type === 'plane') {
    const src = storedToAssemblyPlane(m.sourcePlane)
    const dst = storedToAssemblyPlane(m.targetPlane)
    const dv = matePlaneDeltaVector(sourceGroup, targetGroup, src, dst, 0)
    if (dv) sourceGroup.position.add(dv)
  } else if (m.type === 'distance') {
    const src = storedToAssemblyPlane(m.sourcePlane)
    const dst = storedToAssemblyPlane(m.targetPlane)
    const dv = matePlaneDeltaVector(sourceGroup, targetGroup, src, dst, m.distanceMm)
    if (dv) sourceGroup.position.add(dv)
  } else {
    const b1 = storedToAssemblyPlane(m.base1)
    const b2 = storedToAssemblyPlane(m.base2)
    const p1 = storedToAssemblyPlane(m.part1)
    const p2 = storedToAssemblyPlane(m.part2)
    const dv = mateSymmetricDeltaVector(sourceGroup, targetGroup, b1, b2, p1, p2)
    if (dv) sourceGroup.position.add(dv)
  }
}

function reapplyAllAssemblyMates(): void {
  if (assemblyMates.value.length === 0) return
  meshGroup.updateMatrixWorld(true)
  for (const m of assemblyMates.value) {
    solveStoredMate(m)
  }
  refreshAfterAssemblyMove()
  stripStaleAssemblyFaceTriangles()
  refreshAllAssemblyVisuals()
}

function assemblyMateTypeLabel(m: StoredAssemblyMate): string {
  if (m.type === 'plane') return 'Плоскость'
  if (m.type === 'distance') return 'Расстояние'
  if (m.type === 'coord') return 'Координаты'
  return 'Симметрия'
}

function worldCoordPlaneOptionLabel(id: WorldCoordPlaneId): string {
  return WORLD_COORD_PLANE_OPTIONS.find((o) => o.id === id)?.label ?? id
}

function removeAssemblyMate(id: string) {
  if (selectedAssemblyMateId.value === id) selectedAssemblyMateId.value = null
  assemblyMates.value = assemblyMates.value.filter((x) => x.id !== id)
  if (assemblyMates.value.length > 0) reapplyAllAssemblyMates()
  else refreshAllAssemblyVisuals()
}

function clearAllAssemblyMates() {
  assemblyMates.value = []
  assemblyStatus.value = ''
  clearAssemblyPickStateAfterMateApply()
  stripStaleAssemblyFaceTriangles()
}

function startAssemblyPlanePick(target: Exclude<AssemblyPickTarget, null>) {
  selectedAssemblyMateId.value = null
  assemblyPickTarget.value = target
  const hints: Record<Exclude<AssemblyPickTarget, null>, string> = {
    source: 'Плоскость детали (модель 1): кликните по грани.',
    target: 'Плоскость базы (модель 2): кликните по грани.',
    symBase1: 'База — плоскость 1 (опорная модель): кликните по грани.',
    symBase2: 'База — плоскость 2 (опорная модель): кликните по грани.',
    symPart1: 'Деталь — плоскость 1 (источник): кликните по грани.',
    symPart2: 'Деталь — плоскость 2 (источник): кликните по грани.',
  }
  assemblyStatus.value = hints[target]
  refreshAllAssemblyVisuals()
}

function startCadLinearPlanePick(target: Exclude<CadLinearPickTarget, null>) {
  measureTypeRef.value = 'cad-linear'
  measureModeRef.value = true
  cadLinearPickTarget.value = target
  const hints: Record<Exclude<CadLinearPickTarget, null>, string> = {
    plane1: 'Линейный размер: выберите 1-ю измеряемую плоскость.',
    plane2: 'Линейный размер: выберите 2-ю измеряемую плоскость.',
    display: 'Линейный размер: выберите плоскость отображения размера.',
  }
  cadLinearStatus.value = hints[target]
  measureStatusHint.value = hints[target]
}

function beginNextCadLinearDimension() {
  clearCadLinearPicks()
  measureTypeRef.value = 'cad-linear'
  measureModeRef.value = true
  cadLinearPickTarget.value = 'plane1'
  cadLinearStatus.value = 'Между гранями: кликните 1-ю параллельную грань.'
  measureStatusHint.value = cadLinearStatus.value
}

function clearCadLinearPicks() {
  disposePlanePreviewGeometry(cadLinearPlane1.value ?? undefined)
  disposePlanePreviewGeometry(cadLinearPlane2.value ?? undefined)
  disposePlanePreviewGeometry(cadLinearDisplayPlane.value ?? undefined)
  cadLinearPlane1.value = null
  cadLinearPlane2.value = null
  cadLinearDisplayPlane.value = null
  cadLinearPickTarget.value = null
  refreshMeasurementReferenceFaceHighlights()
}

function startNewCadLinearMeasurement() {
  beginNextCadLinearDimension()
}

function toggleLinearMeasurementRow(id: string) {
  expandedLinearMeasurementIds.value = expandedLinearMeasurementIds.value.includes(id)
    ? expandedLinearMeasurementIds.value.filter((x) => x !== id)
    : [...expandedLinearMeasurementIds.value, id]
}

function saveCadLinearFromPickedPlanes() {
  const p1 = cadLinearPlane1.value
  const p2 = cadLinearPlane2.value
  const pd = cadLinearDisplayPlane.value
  if (!p1 || !p2 || !pd) return
  const n1 = planePickNormalWorld(p1)
  const n2 = planePickNormalWorld(p2)
  if (Math.abs(n1.dot(n2)) < 0.85) {
    cadLinearStatus.value =
      'Плоскости 1 и 2 должны быть параллельны (кликните по другим граням или «Новый размер»).'
    cadLinearPickTarget.value = 'plane2'
    return
  }
  saveCadLinearMeasurement(
    p1.point.clone(),
    p2.point.clone(),
    p1.modelId,
    p2.modelId,
    vecToSaved(p1.meshLocalPoint ?? p1.localPoint),
    vecToSaved(p2.meshLocalPoint ?? p2.localPoint),
    n1,
    n2,
    vecToSaved(p1.normal),
    vecToSaved(p2.normal),
    pd.modelId,
    vecToSaved(pd.localPoint),
    vecToSaved(pd.normal),
    p1.meshUuid ?? null,
    p2.meshUuid ?? null,
  )
  beginNextCadLinearDimension()
  cadLinearStatus.value = 'Размер сохранён. Кликните 1-ю грань для следующего.'
  measureStatusHint.value = cadLinearStatus.value
}

function inferCadLinearPickTarget(): Exclude<CadLinearPickTarget, null> | null {
  if (cadLinearPickTarget.value) return cadLinearPickTarget.value
  if (!cadLinearPlane1.value) return 'plane1'
  if (!cadLinearPlane2.value) return 'plane2'
  return 'display'
}

function autoCadLinearDisplayAndSave() {
  const p1 = cadLinearPlane1.value
  const p2 = cadLinearPlane2.value
  if (!p1 || !p2) {
    cadLinearStatus.value = 'Сначала выберите грани 1 и 2.'
    measureStatusHint.value = cadLinearStatus.value
    return
  }
  cadLinearDisplayPlane.value = buildAutoCadLinearDisplayPlane(p1, p2)
  cadLinearPickTarget.value = null
  saveCadLinearFromPickedPlanes()
}

function meshFromIntersectObject(obj: THREE.Object3D): THREE.Mesh | null {
  let o: THREE.Object3D | null = obj
  while (o) {
    if (o instanceof THREE.Mesh) return o
    o = o.parent
  }
  return null
}

function isObjectWorldVisible(obj: THREE.Object3D): boolean {
  let o: THREE.Object3D | null = obj
  while (o) {
    if (!o.visible) return false
    o = o.parent
  }
  return true
}

function isMeshRayPickable(mesh: THREE.Mesh): boolean {
  if (!isObjectWorldVisible(mesh)) return false
  if (mesh.userData?.wireframeEdge) return false
  if (!findWrapperGroup(mesh)) return false
  const iso = partTreeIsolateState.value
  if (iso) {
    const wrapper = findWrapperGroup(mesh)
    const mid = String(wrapper?.userData?.modelId ?? '')
    if (mid !== iso.modelId) return false
    if (!iso.keepIds.has(mesh.uuid)) return false
  }
  return true
}

function filterPickableHits(hits: THREE.Intersection[]): THREE.Intersection[] {
  return hits.filter((h) => {
    if (h.object.userData?.wireframeEdge) return false
    const mesh = meshFromIntersectObject(h.object)
    if (!mesh || !h.face) return false
    return isMeshRayPickable(mesh)
  })
}

function intersectPickableMeshes(raycaster: THREE.Raycaster): THREE.Intersection[] {
  if (!meshGroup) return []
  return filterPickableHits(raycaster.intersectObject(meshGroup, true))
}

function blockMeshRaycast(mesh: THREE.Mesh) {
  if (!meshRaycastBackup.has(mesh)) meshRaycastBackup.set(mesh, mesh.raycast.bind(mesh))
  mesh.raycast = noopRaycast
}

function restoreMeshRaycast(mesh: THREE.Mesh) {
  const saved = meshRaycastBackup.get(mesh)
  if (saved) {
    mesh.raycast = saved
    meshRaycastBackup.delete(mesh)
  }
}

function applyIsolateRaycastBlocks(modelId: string, keepIds: Set<string>) {
  const g = modelGroupsById.get(modelId)
  if (!g) return
  g.traverse((obj) => {
    if (!(obj instanceof THREE.Mesh)) return
    if (keepIds.has(obj.uuid)) restoreMeshRaycast(obj)
    else blockMeshRaycast(obj)
  })
}

/** Каркас, ghost-материалы и raycast-блокировки для одной модели. */
function purgeModelAuxiliaryState(group: THREE.Group) {
  removeWireframeEdgesFromObject(group)
  group.traverse((obj) => {
    if (!(obj instanceof THREE.Mesh)) return
    restoreMeshRaycast(obj)
    if (wireframeFaceMatBackup.has(obj)) setMeshWireframeFaceGhost(obj, false)
    if (dimmedMeshBackups.has(obj)) {
      const backup = dimmedMeshBackups.get(obj)!
      obj.material = backup.material
      obj.visible = backup.visible
      dimmedMeshBackups.delete(obj)
    }
  })
}

function disposeAllLoadedModels() {
  restorePartTreeIsolate()
  clearPartFocusVisuals()
  wireframeFaceMatBackup.clear()
  meshRaycastBackup.clear()
  const ids = [...modelGroupsById.keys()]
  for (const id of ids) removeModel(id)
}

/** Первое попадание в грань детали (игнорируя линии каркаса и скрытые меши). */
function pickSolidSurfaceHit(hits: THREE.Intersection[]): THREE.Intersection | null {
  for (const h of filterPickableHits(hits)) {
    const mesh = meshFromIntersectObject(h.object)
    if (!mesh || !h.face) continue
    return { ...h, object: mesh }
  }
  return null
}

/** Первое попадание в деталь (игнорируя линии каркаса). */
function firstSolidPartHit(hits: THREE.Intersection[]): { hit: THREE.Intersection; mesh: THREE.Mesh } | null {
  const hit = pickSolidSurfaceHit(hits)
  if (!hit) return null
  return { hit, mesh: hit.object as THREE.Mesh }
}

function firstMeshFaceHit(hits: THREE.Intersection[]): THREE.Intersection | null {
  return pickSolidSurfaceHit(hits)
}

function pickCadLinearPlaneFromHit(hit: THREE.Intersection) {
  const wrapper = findWrapperGroup(hit.object)
  const modelId = String(wrapper?.userData?.modelId ?? '')
  const mesh = hit.object as THREE.Mesh
  const face = hit.face
  if (!wrapper || !modelId || !face) {
    cadLinearStatus.value = 'Не удалось определить грань. Кликните по плоской грани модели.'
    return
  }
  const normal = face.normal.clone().transformDirection(mesh.matrixWorld).normalize()
  const snapped = camera ? getClosestSnapPoint(getSnapCandidates(hit), camera, mouse) : null
  const planePoint = (snapped ?? hit.point).clone()
  const localPoint = wrapper.worldToLocal(planePoint.clone())
  const meshLocalPoint = mesh.worldToLocal(planePoint.clone())
  const tri = buildFaceHighlightGeometryFromHit(hit)
  const localNormal = worldNormalToLocal(wrapper, normal)
  const pick: AssemblyPlaneSelection = {
    modelId,
    point: planePoint,
    localPoint,
    meshUuid: mesh.uuid,
    meshLocalPoint,
    normal: localNormal,
  }
  if (tri) pick.previewGeometry = tri
  const target = inferCadLinearPickTarget()
  if (!target) {
    cadLinearStatus.value = 'Нажмите «Новый размер» или кнопку плоскости 1 / 2 / вывода.'
    return
  }
  if (target === 'plane1') {
    selectedMeasurementId.value = null
    disposePlanePreviewGeometry(cadLinearPlane1.value ?? undefined)
    cadLinearPlane1.value = pick
    cadLinearPickTarget.value = 'plane2'
    cadLinearStatus.value = 'Грань 1 выбрана. Кликните 2-ю параллельную грань.'
    measureStatusHint.value = cadLinearStatus.value
  } else if (target === 'plane2') {
    disposePlanePreviewGeometry(cadLinearPlane2.value ?? undefined)
    cadLinearPlane2.value = pick
    cadLinearPickTarget.value = 'display'
    cadLinearStatus.value = 'Грань 2 выбрана. Кликните плоскость вывода (3-я грань) или «Авто-вынос».'
    measureStatusHint.value = cadLinearStatus.value
  } else {
    disposePlanePreviewGeometry(cadLinearDisplayPlane.value ?? undefined)
    cadLinearDisplayPlane.value = pick
    cadLinearPickTarget.value = null
    cadLinearStatus.value = 'Плоскость вывода выбрана.'
    measureStatusHint.value = cadLinearStatus.value
  }
  if (cadLinearPlane1.value && cadLinearPlane2.value && cadLinearDisplayPlane.value) {
    saveCadLinearFromPickedPlanes()
  }
  refreshMeasurementReferenceFaceHighlights()
}

function inferAutoAssemblyPickTarget(modelId: string): Exclude<AssemblyPickTarget, null> | null {
  const srcId = assemblySourceModelId.value
  const tgtId = assemblyTargetModelId.value
  if (assemblyMateType.value === 'coord') {
    if (!srcId || modelId !== srcId) return null
    return 'source'
  }
  if (!srcId || !tgtId) return null
  if (assemblyMateType.value === 'symmetric') {
    if (modelId === tgtId) {
      if (!assemblySymBase1.value) return 'symBase1'
      if (!assemblySymBase2.value) return 'symBase2'
      return 'symBase1'
    }
    if (modelId === srcId) {
      if (!assemblySymPart1.value) return 'symPart1'
      if (!assemblySymPart2.value) return 'symPart2'
      return 'symPart1'
    }
    return null
  }
  if (modelId === srcId) {
    if (!assemblySourcePlane.value) return 'source'
    return 'source'
  }
  if (modelId === tgtId) {
    if (!assemblyTargetPlane.value) return 'target'
    return 'target'
  }
  return null
}

function pickAssemblyPlaneFromHit(hit: THREE.Intersection) {
  const wrapper = findWrapperGroup(hit.object)
  const modelId = String(wrapper?.userData?.modelId ?? '')
  if (!wrapper || !modelId) {
    assemblyStatus.value = 'Не удалось определить модель для выбранной грани.'
    assemblyPickTarget.value = null
    return
  }
  const built = buildAssemblyPlaneFromHit(hit, wrapper, modelId)
  if (!built.pick) {
    assemblyStatus.value = built.error ?? 'Не удалось выбрать грань.'
    assemblyPickTarget.value = null
    return
  }
  const pick = built.pick
  const t = assemblyPickTarget.value
  if (!t) {
    assemblyStatus.value = 'Выберите поле плоскости в панели сборки или кликните по грани (автовыбор).'
    return
  }
  const srcId = assemblySourceModelId.value
  const tgtId = assemblyTargetModelId.value
  if (assemblyMateType.value === 'coord') {
    if (!srcId || modelId !== srcId) {
      assemblyStatus.value = 'Координаты: кликните по грани модели-источника.'
      assemblyPickTarget.value = null
      return
    }
  } else if (t === 'source' || t === 'symPart1' || t === 'symPart2') {
    if (!srcId || modelId !== srcId) {
      assemblyStatus.value = 'Кликните по грани модели-источника (модель 1).'
      assemblyPickTarget.value = null
      return
    }
  }
  if (t === 'target' || t === 'symBase1' || t === 'symBase2') {
    if (!tgtId || modelId !== tgtId) {
      assemblyStatus.value = 'Кликните по грани опорной модели (модель 2 / база).'
      assemblyPickTarget.value = null
      return
    }
  }
  if (t === 'source') {
    disposePlanePreviewGeometry(assemblySourcePlane.value ?? undefined)
    assemblySourcePlane.value = pick
    assemblyStatus.value = 'Плоскость детали (модель 1) выбрана.'
  } else if (t === 'target') {
    disposePlanePreviewGeometry(assemblyTargetPlane.value ?? undefined)
    assemblyTargetPlane.value = pick
    assemblyStatus.value = 'Плоскость базы (модель 2) выбрана.'
  } else if (t === 'symBase1') {
    disposePlanePreviewGeometry(assemblySymBase1.value ?? undefined)
    assemblySymBase1.value = pick
    assemblyStatus.value = 'База: плоскость 1 выбрана.'
  } else if (t === 'symBase2') {
    disposePlanePreviewGeometry(assemblySymBase2.value ?? undefined)
    assemblySymBase2.value = pick
    assemblyStatus.value = 'База: плоскость 2 выбрана.'
  } else if (t === 'symPart1') {
    disposePlanePreviewGeometry(assemblySymPart1.value ?? undefined)
    assemblySymPart1.value = pick
    assemblyStatus.value = 'Деталь: плоскость 1 выбрана.'
  } else if (t === 'symPart2') {
    disposePlanePreviewGeometry(assemblySymPart2.value ?? undefined)
    assemblySymPart2.value = pick
    assemblyStatus.value = 'Деталь: плоскость 2 выбрана.'
  }
  assemblyPickTarget.value = null
  selectedAssemblyMateId.value = null
  refreshAllAssemblyVisuals()
}

function applyAssemblyMate() {
  const sourceId = assemblySourceModelId.value
  const targetId = assemblyTargetModelId.value
  if (!sourceId) {
    assemblyStatus.value = 'Выберите модель-источник.'
    return
  }
  const sourceGroup = modelGroupsById.get(sourceId)
  const sourceBox = getAssemblyModelBox(sourceId)
  if (!sourceGroup || !sourceBox) {
    assemblyStatus.value = 'Модель-источник не в сцене или не имеет геометрии.'
    return
  }

  if (assemblyMateType.value === 'coord') {
    const srcPlane = assemblySourcePlane.value
    if (!srcPlane || srcPlane.modelId !== sourceId) {
      assemblyStatus.value = 'Выберите плоскость на модели (кнопка «Выбрать» и клик по грани).'
      return
    }
    const distance = Math.max(0, Number(assemblyDistanceMm.value) || 0)
    const result = applyCoordPlaneMateToGroup(
      sourceGroup,
      srcPlane,
      assemblyCoordWorldPlane.value,
      distance,
      assemblyCoordFlipNormal.value,
    )
    if (!result.ok) {
      assemblyStatus.value = result.message
      return
    }
    assemblyMates.value = [
      ...assemblyMates.value,
      {
        id: newAssemblyMateId(),
        type: 'coord',
        sourceId,
        sourcePlane: persistAssemblyPlane(srcPlane),
        worldPlane: assemblyCoordWorldPlane.value,
        distanceMm: distance,
        flipNormal: assemblyCoordFlipNormal.value,
      },
    ]
    refreshAfterAssemblyMove()
    assemblyStatus.value = `Сопряжение зафиксировано: ${result.message}. Для выравнивания по другой оси добавьте второе сопряжение к другой грани.`
    clearAssemblyPickStateAfterMateApply()
    return
  }

  if (!targetId) {
    assemblyStatus.value = 'Выберите опорную модель.'
    return
  }
  if (sourceId === targetId) {
    assemblyStatus.value = 'Источник и опорная модель должны отличаться.'
    return
  }
  const targetGroup = modelGroupsById.get(targetId)
  const targetBox = getAssemblyModelBox(targetId)
  if (!targetGroup || !targetBox) {
    assemblyStatus.value = 'Опорная модель не в сцене или не имеет геометрии.'
    return
  }
  const axis = assemblyAxis.value
  let delta = 0
  if (assemblyMateType.value === 'symmetric') {
    const b1 = assemblySymBase1.value
    const b2 = assemblySymBase2.value
    const p1 = assemblySymPart1.value
    const p2 = assemblySymPart2.value
    if (!b1 || !b2 || !p1 || !p2) {
      assemblyStatus.value = 'Симметрия: выберите 4 плоскости (2 базы + 2 детали).'
      return
    }
    if (b1.modelId !== targetId || b2.modelId !== targetId) {
      assemblyStatus.value = 'Плоскости базы должны принадлежать опорной модели.'
      return
    }
    if (p1.modelId !== sourceId || p2.modelId !== sourceId) {
      assemblyStatus.value = 'Плоскости детали должны принадлежать модели-источнику.'
      return
    }
    const dv = mateSymmetricDeltaVector(sourceGroup, targetGroup, b1, b2, p1, p2)
    if (!dv) {
      assemblyStatus.value = 'Не удалось вычислить симметрию: плоскости должны быть параллельны (пара базы и пара детали).'
      return
    }
    sourceGroup.position.add(dv)
    assemblyMates.value = [
      ...assemblyMates.value,
      {
        id: newAssemblyMateId(),
        type: 'symmetric',
        sourceId,
        targetId,
        base1: persistAssemblyPlane(b1),
        base2: persistAssemblyPlane(b2),
        part1: persistAssemblyPlane(p1),
        part2: persistAssemblyPlane(p2),
      },
    ]
    refreshAfterAssemblyMove()
    assemblyStatus.value = `Сопряжение зафиксировано: симметрия по ширине, |Δ|=${dv.length().toFixed(2)} мм`
    clearAssemblyPickStateAfterMateApply()
    return
  }
  if (assemblySourcePlane.value && assemblyTargetPlane.value) {
    const srcPlane = assemblySourcePlane.value
    const dstPlane = assemblyTargetPlane.value
    if (srcPlane.modelId !== sourceId || dstPlane.modelId !== targetId) {
      assemblyStatus.value = 'Плоскости должны соответствовать источнику и опорной модели.'
      return
    }
    const distance = assemblyMateType.value === 'distance' ? Math.max(0, Number(assemblyDistanceMm.value) || 0) : 0
    const nwDst = dstPlane.normal.clone().transformDirection(targetGroup.matrixWorld).normalize()
    alignSourcePlaneNormalToWorld(sourceGroup, srcPlane, nwDst, false)
    const dv = matePlaneDeltaVector(sourceGroup, targetGroup, srcPlane, dstPlane, distance)
    if (!dv) {
      assemblyStatus.value = 'Не удалось совместить плоскости после поворота — проверьте выбор граней.'
      return
    }
    updatePlaneSelectionNormalToWorld(srcPlane, sourceGroup, nwDst)
    sourceGroup.position.add(dv)
    if (assemblyMateType.value === 'distance') {
      assemblyMates.value = [
        ...assemblyMates.value,
        {
          id: newAssemblyMateId(),
          type: 'distance',
          sourceId,
          targetId,
          sourcePlane: persistAssemblyPlane(srcPlane),
          targetPlane: persistAssemblyPlane(dstPlane),
          distanceMm: distance,
        },
      ]
    } else {
      assemblyMates.value = [
        ...assemblyMates.value,
        {
          id: newAssemblyMateId(),
          type: 'plane',
          sourceId,
          targetId,
          sourcePlane: persistAssemblyPlane(srcPlane),
          targetPlane: persistAssemblyPlane(dstPlane),
        },
      ]
    }
    refreshAfterAssemblyMove()
    assemblyStatus.value =
      assemblyMateType.value === 'distance'
        ? `Сопряжение зафиксировано: зазор между гранями ${distance.toFixed(2)} мм (|Δ|=${dv.length().toFixed(2)} мм)`
        : `Сопряжение зафиксировано: совмещение плоскостей (|Δ|=${dv.length().toFixed(2)} мм)`
    clearAssemblyPickStateAfterMateApply()
    return
  }
  const sourceSideValue = getAxisSideValue(sourceBox, axis, assemblySourceSide.value)
  const targetSideValue = getAxisSideValue(targetBox, axis, assemblyTargetSide.value)
  const distance = assemblyMateType.value === 'distance' ? Math.max(0, Number(assemblyDistanceMm.value) || 0) : 0
  const sideSign = assemblySourceSide.value === 'min' ? 1 : -1
  const desiredSourceValue = targetSideValue + sideSign * distance
  delta = desiredSourceValue - sourceSideValue
  moveGroupAlongAxis(sourceGroup, axis, delta)
  refreshAfterAssemblyMove()
  assemblyStatus.value = `Применено (по габаритам bbox): Δ${axis.toUpperCase()}=${delta.toFixed(2)} мм — не сохраняется как связь; для связи выберите плоскости.`
}

function clampTintBrightness(v: number): number {
  return Math.min(TINT_BRIGHTNESS_MAX, Math.max(TINT_BRIGHTNESS_MIN, v))
}

function onTintBrightnessInput(ev: Event) {
  const val = Number((ev.target as HTMLInputElement).value)
  if (!Number.isFinite(val)) return
  tintBrightness.value = clampTintBrightness(val)
  applyModelTint()
  applySceneLightingForShadingMode()
}

function onTintBrightnessWheel(ev: WheelEvent) {
  const delta = ev.deltaY > 0 ? -TINT_BRIGHTNESS_STEP : TINT_BRIGHTNESS_STEP
  tintBrightness.value = clampTintBrightness(tintBrightness.value + delta)
  applyModelTint()
  applySceneLightingForShadingMode()
}

function clampColorVividness(v: number): number {
  return Math.min(COLOR_VIVIDNESS_MAX, Math.max(COLOR_VIVIDNESS_MIN, v))
}

function onColorVividnessInput(ev: Event) {
  const val = Number((ev.target as HTMLInputElement).value)
  if (!Number.isFinite(val)) return
  colorVividness.value = clampColorVividness(val)
  refreshImportedPartColors()
}

function refreshImportedPartColors() {
  if (!meshGroup) return
  meshGroup.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh)) return
    const hex = obj.userData?.partColorHex as string | undefined
    if (hex) applyHexToMesh(obj, hex)
  })
}

function applySceneBackground() {
  if (!scene) return
  scene.background = new THREE.Color(sceneBackgroundHex.value)
}

function onSceneBackgroundInput(ev: Event) {
  const val = (ev.target as HTMLInputElement).value
  if (!val) return
  sceneBackgroundHex.value = val
  applySceneBackground()
}

function onExtraLightsChange() {
  applySceneLightingForShadingMode()
}

function openSettingsModal() {
  settingsModalOpen.value = true
}

function closeSettingsModal() {
  settingsModalOpen.value = false
}

function ensureModelUnitsMillimeters(wrapper: THREE.Group): void {
  if (wrapper.userData?.unitsNormalized === 'mm') return
  const box = new THREE.Box3().setFromObject(wrapper)
  if (box.isEmpty()) return
  const size = box.getSize(new THREE.Vector3())
  const maxAxis = Math.max(size.x, size.y, size.z)
  if (maxAxis >= METERS_LIKELY_MAX_AXIS) {
    wrapper.userData.unitsNormalized = 'mm'
    return
  }
  wrapper.scale.multiplyScalar(METERS_TO_MM_SCALE)
  wrapper.userData.unitsNormalized = 'mm'
  wrapper.userData.unitScaleFromMeters = METERS_TO_MM_SCALE
}

function getReferenceSceneBox(): THREE.Box3 | null {
  if (focusedModelId.value) {
    const g = modelGroupsById.get(focusedModelId.value)
    if (g) {
      const b = new THREE.Box3().setFromObject(g)
      if (!b.isEmpty()) return b
    }
  }
  for (const m of loadedModels.value) {
    if (!m.inScene) continue
    const g = modelGroupsById.get(m.id)
    if (!g) continue
    const b = new THREE.Box3().setFromObject(g)
    if (!b.isEmpty()) return b
  }
  if (meshGroup?.children.length) {
    const b = new THREE.Box3().setFromObject(meshGroup)
    if (!b.isEmpty()) return b
  }
  return null
}

function refreshScenePresentationFromReference() {
  const refBox = getReferenceSceneBox()
  const sceneBox = getFullSceneBox()
  const sizingBox = sceneBox ?? refBox
  if (!sizingBox) return
  const size = sizingBox.getSize(new THREE.Vector3())
  loadedSceneCharDim = Math.max(size.x, size.y, size.z, 1)
  updateGroundGrid(sizingBox)
  updateSceneLighting(refBox ?? sizingBox)
  syncWorldCoordSystemGroup()
}

function applyNavigationForFocusedModel() {
  applyAutoNavigationLimits()
}

watch(focusedModelId, (id) => {
  if (id) expandedModelIds.value = { ...expandedModelIds.value, [id]: true }
  if (!scene) return
  refreshScenePresentationFromReference()
  applyNavigationForFocusedModel()
})

watch(colorVividness, () => {
  refreshImportedPartColors()
})

function calculateSceneMetrics(): { areaMm2: number; volumeMm3: number; triangles: number } {
  if (!meshGroup) return { areaMm2: 0, volumeMm3: 0, triangles: 0 }
  meshGroup.updateMatrixWorld(true)
  let area = 0
  let volume = 0
  let triangles = 0
  const va = new THREE.Vector3()
  const vb = new THREE.Vector3()
  const vc = new THREE.Vector3()
  const ab = new THREE.Vector3()
  const ac = new THREE.Vector3()
  const cross = new THREE.Vector3()

  const accumulateTriangle = (ia: number, ib: number, ic: number, pos: THREE.BufferAttribute, mw: THREE.Matrix4) => {
    va.fromBufferAttribute(pos, ia).applyMatrix4(mw)
    vb.fromBufferAttribute(pos, ib).applyMatrix4(mw)
    vc.fromBufferAttribute(pos, ic).applyMatrix4(mw)
    ab.subVectors(vb, va)
    ac.subVectors(vc, va)
    cross.crossVectors(ab, ac)
    area += 0.5 * cross.length()
    volume += va.dot(cross) / 6
    triangles++
  }

  meshGroup.traverse((obj) => {
    if (!(obj instanceof THREE.Mesh) || !obj.visible) return
    const geom = obj.geometry
    if (!(geom instanceof THREE.BufferGeometry)) return
    const pos = geom.getAttribute('position')
    if (!(pos instanceof THREE.BufferAttribute)) return
    const idx = geom.getIndex()
    const mw = obj.matrixWorld
    if (idx) {
      const arr = idx.array
      for (let i = 0; i < arr.length; i += 3) {
        accumulateTriangle(arr[i] as number, arr[i + 1] as number, arr[i + 2] as number, pos, mw)
      }
    } else {
      for (let i = 0; i < pos.count; i += 3) {
        accumulateTriangle(i, i + 1, i + 2, pos, mw)
      }
    }
  })

  return { areaMm2: area, volumeMm3: Math.abs(volume), triangles }
}

function scheduleSceneMetricsRecalc() {
  const jobId = ++metricsJobSeq
  if (!meshGroup || meshGroup.children.length === 0) {
    sceneSurfaceAreaMm2.value = null
    sceneVolumeMm3.value = null
    sceneTriangles.value = 0
    isMetricsCalculating.value = false
    return
  }
  isMetricsCalculating.value = true
  setTimeout(() => {
    if (jobId !== metricsJobSeq) return
    const m = calculateSceneMetrics()
    if (jobId !== metricsJobSeq) return
    sceneSurfaceAreaMm2.value = m.areaMm2
    sceneVolumeMm3.value = m.volumeMm3
    sceneTriangles.value = m.triangles
    isMetricsCalculating.value = false
  }, 0)
}

const sceneMetricsText = computed(() => {
  if (isMetricsCalculating.value) return 'Расчет площади/объема...'
  if (sceneSurfaceAreaMm2.value == null || sceneVolumeMm3.value == null) return 'Площадь/объем: —'
  const areaM2 = sceneSurfaceAreaMm2.value / 1_000_000
  const volumeL = sceneVolumeMm3.value / 1_000_000
  return `S: ${areaM2.toFixed(3)} м² | V: ${volumeL.toFixed(3)} л | △ ${sceneTriangles.value.toLocaleString('ru-RU')}`
})
const dimArrowSizeMm = ref(8)
const dimLineOffsetMm = ref(18)
const dimFontSizeMm = ref(12)
const measureStatusHint = ref('')
const expandedLinearMeasurementIds = ref<string[]>([])

type LinearDimGeometry = {
  srcA: THREE.Vector3
  srcB: THREE.Vector3
  dimA: THREE.Vector3
  dimB: THREE.Vector3
  labelWorld: THREE.Vector3
}

function defaultMeasurementLineOffsetMm(): number {
  return Math.max(dimLineOffsetMm.value, loadedSceneCharDim * 0.028)
}

function buildSavedDisplayPlaneFields(
  mid: THREE.Vector3,
  anchorModelId: string | null,
): {
  outputPlaneModelId: string | null
  outputPlaneLocalPoint: SavedVec3 | null
  outputPlaneLocalNormal: SavedVec3 | null
} {
  if (!anchorModelId || !camera) {
    return { outputPlaneModelId: null, outputPlaneLocalPoint: null, outputPlaneLocalNormal: null }
  }
  const g = modelGroupsById.get(anchorModelId)
  if (!g) {
    return { outputPlaneModelId: null, outputPlaneLocalPoint: null, outputPlaneLocalNormal: null }
  }
  const viewNormal = mid.clone().sub(camera.position).normalize()
  return {
    outputPlaneModelId: anchorModelId,
    outputPlaneLocalPoint: vecToSaved(g.worldToLocal(mid.clone())),
    outputPlaneLocalNormal: vecToSaved(worldNormalToLocal(g, viewNormal)),
  }
}

function planePickNormalWorld(pick: AssemblyPlaneSelection): THREE.Vector3 {
  const g = modelGroupsById.get(pick.modelId)
  if (g) return localNormalToWorld(g, vecToSaved(pick.normal)) ?? savedToVec(pick.normal)
  return savedToVec(pick.normal)
}

function buildLinearDimGeometry(
  srcA: THREE.Vector3,
  srcB: THREE.Vector3,
  planeNormal: THREE.Vector3,
  lineOffsetMm: number,
): LinearDimGeometry {
  const dir = srcB.clone().sub(srcA)
  if (dir.lengthSq() < 1e-12) dir.set(1, 0, 0)
  else dir.normalize()
  const n = planeNormal.clone().normalize()
  let offsetDir = new THREE.Vector3().crossVectors(dir, n).normalize()
  if (offsetDir.lengthSq() < 0.01) offsetDir = new THREE.Vector3(0, 0, 1)
  offsetDir = orientOffsetDirForScreen(offsetDir, srcA.clone().add(srcB).multiplyScalar(0.5))
  const off = normalizeSignedOffset(lineOffsetMm)
  const dimA = srcA.clone().add(offsetDir.clone().multiplyScalar(off))
  const dimB = srcB.clone().add(offsetDir.clone().multiplyScalar(off))
  return {
    srcA: srcA.clone(),
    srcB: srcB.clone(),
    dimA,
    dimB,
    labelWorld: dimA.clone().add(dimB).multiplyScalar(0.5),
  }
}

function linearDimLabelWorldForAnchorPoints(
  a: THREE.Vector3,
  b: THREE.Vector3,
  lineOffsetMm = defaultMeasurementLineOffsetMm(),
  planeNormal?: THREE.Vector3,
): THREE.Vector3 {
  const mid = a.clone().add(b).multiplyScalar(0.5)
  const n = planeNormal?.clone().normalize()
    ?? (camera ? mid.clone().sub(camera.position).normalize() : new THREE.Vector3(0, 1, 0))
  return buildLinearDimGeometry(a, b, n, lineOffsetMm).labelWorld
}

function displayPlaneNormalForSavedRow(row: SavedMeasurement, mid: THREE.Vector3): THREE.Vector3 {
  if (row.outputPlaneLocalNormal) {
    if (row.outputPlaneModelId) {
      const g = modelGroupsById.get(row.outputPlaneModelId)
      if (g) return (localNormalToWorld(g, row.outputPlaneLocalNormal) ?? savedToVec(row.outputPlaneLocalNormal)).normalize()
    }
    return savedToVec(row.outputPlaneLocalNormal).normalize()
  }
  const nA = resolveSavedNormalWorld(row.modelId1, row.n1Local, row.n1, row.meshUuid1)
  const nB = resolveSavedNormalWorld(row.modelId2, row.n2Local, row.n2, row.meshUuid2)
  const faceN = nB ?? nA
  if (faceN) return faceN.clone().normalize()
  if (camera) return mid.clone().sub(camera.position).normalize()
  return new THREE.Vector3(0, 1, 0)
}

function resolveLinearDimForDistanceRow(row: SavedMeasurement): LinearDimGeometry | null {
  const a = resolveSavedPointWorld(row.modelId1, row.p1Local, row.p1, row.meshUuid1)
  const b = resolveSavedPointWorld(row.modelId2, row.p2Local, row.p2, row.meshUuid2)
  const mid = a.clone().add(b).multiplyScalar(0.5)
  return buildLinearDimGeometry(
    a,
    b,
    displayPlaneNormalForSavedRow(row, mid),
    row.lineOffsetMm ?? defaultMeasurementLineOffsetMm(),
  )
}

function resolveLinearDimForCadLinearRow(row: SavedMeasurement): LinearDimGeometry | null {
  const a = resolveSavedPointWorld(row.modelId1, row.p1Local, row.p1, row.meshUuid1)
  const b = resolveSavedPointWorld(row.modelId2, row.p2Local, row.p2, row.meshUuid2)
  let planePoint = row.outputPlaneLocalPoint ? savedToVec(row.outputPlaneLocalPoint) : a.clone()
  let planeNormal = row.outputPlaneLocalNormal ? savedToVec(row.outputPlaneLocalNormal) : new THREE.Vector3(0, 1, 0)
  if (row.outputPlaneModelId) {
    const g = modelGroupsById.get(row.outputPlaneModelId)
    if (g) {
      planePoint = g.localToWorld(planePoint)
      planeNormal = localNormalToWorld(g, vecToSaved(planeNormal)) ?? planeNormal
    }
  }
  const n = planeNormal.clone().normalize()
  const project = (p: THREE.Vector3) => p.clone().sub(n.clone().multiplyScalar(p.clone().sub(planePoint).dot(n)))
  const nA = resolveSavedNormalWorld(row.modelId1, row.n1Local, row.n1, row.meshUuid1)
  const nB = resolveSavedNormalWorld(row.modelId2, row.n2Local, row.n2, row.meshUuid2)
  const strict = projectPerpendicularByNormals(a, b, nA, nB)
  const srcA = strict ? strict.projected : project(a)
  const srcB = strict ? strict.otherPoint : project(b)
  return buildLinearDimGeometry(srcA, srcB, n, row.lineOffsetMm ?? defaultMeasurementLineOffsetMm())
}

function buildAutoCadLinearDisplayPlane(
  p1: AssemblyPlaneSelection,
  p2: AssemblyPlaneSelection,
): AssemblyPlaneSelection {
  const mid = p1.point.clone().add(p2.point).multiplyScalar(0.5)
  const viewNormal = camera
    ? mid.clone().sub(camera.position).normalize()
    : p1.normal.clone().normalize()
  const g = modelGroupsById.get(p1.modelId)
  const localNormal = g ? worldNormalToLocal(g, viewNormal) : viewNormal.clone()
  return {
    modelId: p1.modelId,
    point: mid,
    localPoint: g ? vecToSaved(g.worldToLocal(mid.clone())) : vecToSaved(mid),
    normal: localNormal,
    meshUuid: p1.meshUuid ?? null,
    meshLocalPoint: p1.meshLocalPoint,
  }
}

function syncSavedMeasurementLabelElements() {
  if (!savedMeasurementLabelsLayer) return
  const ids = new Set(measurementHistory.value.map((m) => m.id))
  for (const [id, el] of savedMeasurementLabelById) {
    if (!ids.has(id)) {
      el.remove()
      savedMeasurementLabelById.delete(id)
    }
  }
  for (const row of measurementHistory.value) {
    if (row.type !== 'distance' && row.type !== 'cad-linear') continue
    if (savedMeasurementLabelById.has(row.id)) continue
    const el = document.createElement('div')
    el.className = 'measurement-label saved-measurement-label'
    el.style.cssText =
      'position:absolute;pointer-events:none;color:#fff;background:rgba(12,18,32,0.88);padding:3px 10px;border-radius:4px;font-size:13px;font-weight:600;white-space:nowrap;display:none;border:1px solid rgba(255,173,91,0.75);z-index:6;transform:translate(-50%,-50%);'
    savedMeasurementLabelsLayer.appendChild(el)
    savedMeasurementLabelById.set(row.id, el)
  }
}

function updateSavedMeasurementLabelPositions() {
  if (!camera || !containerRef.value) return
  const rect = containerRef.value.getBoundingClientRect()
  for (const row of measurementHistory.value) {
    const el = savedMeasurementLabelById.get(row.id)
    if (!el) continue
    if (row.type !== 'distance' && row.type !== 'cad-linear') {
      el.style.display = 'none'
      continue
    }
    const geom = row.type === 'distance'
      ? resolveLinearDimForDistanceRow(row)
      : resolveLinearDimForCadLinearRow(row)
    if (!geom) {
      el.style.display = 'none'
      continue
    }
    const p = geom.labelWorld.clone().project(camera)
    if (p.z > 1) {
      el.style.display = 'none'
      continue
    }
    el.style.left = `${(p.x * 0.5 + 0.5) * rect.width}px`
    el.style.top = `${(-p.y * 0.5 + 0.5) * rect.height}px`
    el.textContent = `${measurementValueText(row)} мм`
    el.style.borderColor = row.id === selectedMeasurementId.value ? '#ffffff' : 'rgba(255,173,91,0.75)'
    el.style.display = 'block'
  }
}

function clearSavedMeasurementLabelElements() {
  for (const el of savedMeasurementLabelById.values()) el.remove()
  savedMeasurementLabelById.clear()
}
let draggedMeasurementOffset:
  | {
      id: string
      startX: number
      startY: number
      startOffset: number
      axisX: number
      axisY: number
    }
  | null = null
/** Кандидат на drag выноса — активируется только после сдвига мыши, чтобы не блокировать клик. */
let offsetDragPending:
  | {
      id: string
      startX: number
      startY: number
      startOffset: number
      axisX: number
      axisY: number
    }
  | null = null

/** Мин. смещение preview-точки (мм²), чтобы не перерисовывать линию на каждый пиксель. */
const MEASURE_PREVIEW_MOVE_THRESH_MM2 = 4
/** Порог попадания в линию размера (пиксели) — только для перетаскивания выноса. */
const DIM_LINE_PICK_THRESHOLD_PX = 24
/** Ниже этого сдвига (px) считаем кликом, а не drag выноса. */
const DIM_DRAG_MIN_PX = 5

function isDistancePointPlacementActive(): boolean {
  return measureModeRef.value && measureTypeRef.value === 'distance' && measurementPoints.length > 0
}

function isCadLinearPlanePlacementActive(): boolean {
  return measureModeRef.value && measureTypeRef.value === 'cad-linear' && !!(cadLinearPlane1.value || cadLinearPlane2.value)
}

function shouldDeferSavedMeasurementPick(): boolean {
  return isDistancePointPlacementActive() || isCadLinearPlanePlacementActive()
}

function commitMeasurementLineOffset(id: string, lineOffsetMm: number) {
  measurementHistory.value = measurementHistory.value.map((m) =>
    m.id === id ? { ...m, lineOffsetMm } : m,
  )
}

function screenDistToSegmentPx(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): number {
  const dx = x2 - x1
  const dy = y2 - y1
  const lenSq = dx * dx + dy * dy
  if (lenSq < 1e-6) return Math.hypot(px - x1, py - y1)
  let t = ((px - x1) * dx + (py - y1) * dy) / lenSq
  t = Math.max(0, Math.min(1, t))
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
}

function offsetDragAxisForLinearRow(row: SavedMeasurement, rect: DOMRect): { axisX: number; axisY: number } {
  const anchorWorld = resolveSavedPointWorld(row.modelId1, row.p1Local, row.p1, row.meshUuid1)
    .clone()
    .add(resolveSavedPointWorld(row.modelId2, row.p2Local, row.p2, row.meshUuid2))
    .multiplyScalar(0.5)
  const dirWorld = (() => {
    const a = resolveSavedPointWorld(row.modelId1, row.p1Local, row.p1, row.meshUuid1)
    const b = resolveSavedPointWorld(row.modelId2, row.p2Local, row.p2, row.meshUuid2)
    if (row.type === 'cad-linear') {
      let planePoint = row.outputPlaneLocalPoint ? savedToVec(row.outputPlaneLocalPoint) : a.clone()
      let planeNormal = row.outputPlaneLocalNormal ? savedToVec(row.outputPlaneLocalNormal) : new THREE.Vector3(0, 1, 0)
      if (row.outputPlaneModelId) {
        const g = modelGroupsById.get(row.outputPlaneModelId)
        if (g) {
          planePoint = g.localToWorld(planePoint)
          planeNormal = localNormalToWorld(g, vecToSaved(planeNormal)) ?? planeNormal
        }
      }
      const n = planeNormal.clone().normalize()
      const project = (p: THREE.Vector3) => p.clone().sub(n.clone().multiplyScalar(p.clone().sub(planePoint).dot(n)))
      const nA = resolveSavedNormalWorld(row.modelId1, row.n1Local, row.n1, row.meshUuid1)
      const nB = resolveSavedNormalWorld(row.modelId2, row.n2Local, row.n2, row.meshUuid2)
      const strict = projectPerpendicularByNormals(a, b, nA, nB)
      const srcA = strict ? strict.projected : project(a)
      const srcB = strict ? strict.otherPoint : project(b)
      const dir = srcB.clone().sub(srcA).normalize()
      let offsetDir = new THREE.Vector3().crossVectors(dir, n).normalize()
      if (offsetDir.lengthSq() < 0.01) offsetDir = new THREE.Vector3(0, 0, 1)
      return orientOffsetDirForScreen(offsetDir, srcA.clone().add(srcB).multiplyScalar(0.5))
    }
    const mid = a.clone().add(b).multiplyScalar(0.5)
    const n = displayPlaneNormalForSavedRow(row, mid)
    const dir = b.clone().sub(a).normalize()
    let offsetDir = new THREE.Vector3().crossVectors(dir, n).normalize()
    if (offsetDir.lengthSq() < 0.01) offsetDir = new THREE.Vector3(0, 0, 1)
    return orientOffsetDirForScreen(offsetDir, mid)
  })()
  if (!camera) return { axisX: 0, axisY: -1 }
  const p0 = anchorWorld.clone().project(camera)
  const p1 = anchorWorld.clone().add(dirWorld.clone().multiplyScalar(100)).project(camera)
  let axisX = (p1.x - p0.x) * rect.width * 0.5
  let axisY = -(p1.y - p0.y) * rect.height * 0.5
  const axisLen = Math.hypot(axisX, axisY)
  if (axisLen > 1e-3) {
    axisX /= axisLen
    axisY /= axisLen
  } else {
    axisX = 0
    axisY = -1
  }
  return { axisX, axisY }
}

function pickLinearMeasurementAtClient(clientX: number, clientY: number): SavedMeasurement | null {
  if (!camera || !renderer || !savedMeasurementsGroup) return null
  const rect = renderer.domElement.getBoundingClientRect()
  const mx = ((clientX - rect.left) / rect.width) * 2 - 1
  const my = -((clientY - rect.top) / rect.height) * 2 + 1
  savedMeasurementsGroup.updateMatrixWorld(true)
  const rr = new THREE.Raycaster()
  rr.params.Line = { threshold: DIM_LINE_PICK_THRESHOLD_PX }
  rr.setFromCamera(new THREE.Vector2(mx, my), camera)
  for (const h of rr.intersectObject(savedMeasurementsGroup, true)) {
    const id = String((h.object as THREE.Object3D).userData?.measurementId ?? '')
    if (!id) continue
    const row = measurementHistory.value.find((m) => m.id === id)
    if (row && (row.type === 'distance' || row.type === 'cad-linear')) return row
  }
  const px = clientX - rect.left
  const py = clientY - rect.top
  let bestRow: SavedMeasurement | null = null
  let bestDist = DIM_LINE_PICK_THRESHOLD_PX
  const toScreen = (v: THREE.Vector3) => {
    const p = v.clone().project(camera!)
    return { x: (p.x * 0.5 + 0.5) * rect.width, y: (-p.y * 0.5 + 0.5) * rect.height, z: p.z }
  }
  for (const row of measurementHistory.value) {
    if (row.type !== 'distance' && row.type !== 'cad-linear') continue
    const dim = row.type === 'distance'
      ? resolveLinearDimForDistanceRow(row)
      : resolveLinearDimForCadLinearRow(row)
    if (!dim) continue
    const segments: [THREE.Vector3, THREE.Vector3][] = [
      [dim.srcA, dim.dimA],
      [dim.srcB, dim.dimB],
      [dim.dimA, dim.dimB],
    ]
    for (const [a, b] of segments) {
      const sa = toScreen(a)
      const sb = toScreen(b)
      if (sa.z > 1 && sb.z > 1) continue
      const d = screenDistToSegmentPx(px, py, sa.x, sa.y, sb.x, sb.y)
      if (d < bestDist) {
        bestDist = d
        bestRow = row
      }
    }
  }
  return bestRow
}

function tryBeginMeasurementOffsetDrag(ev: MouseEvent): boolean {
  if (ev.button !== 0 || !savedMeasurementsGroup || !renderer || shouldDeferSavedMeasurementPick()) return false
  const row = pickLinearMeasurementAtClient(ev.clientX, ev.clientY)
  if (!row) return false
  if (selectedMeasurementId.value !== row.id) {
    selectedMeasurementId.value = row.id
    rebuildSavedMeasurementsVisuals()
  }
  const rect = renderer.domElement.getBoundingClientRect()
  const { axisX, axisY } = offsetDragAxisForLinearRow(row, rect)
  offsetDragPending = {
    id: row.id,
    startX: ev.clientX,
    startY: ev.clientY,
    startOffset: row.lineOffsetMm ?? defaultMeasurementLineOffsetMm(),
    axisX,
    axisY,
  }
  ev.preventDefault()
  ev.stopPropagation()
  return true
}

function vecToSaved(v: THREE.Vector3): SavedVec3 {
  return { x: v.x, y: v.y, z: v.z }
}

function savedToVec(v: SavedVec3): THREE.Vector3 {
  return new THREE.Vector3(v.x, v.y, v.z)
}

function worldNormalToLocal(group: THREE.Group, n: THREE.Vector3): THREE.Vector3 {
  const inv = group.matrixWorld.clone().invert()
  return n.clone().transformDirection(inv).normalize()
}

function localNormalToWorld(group: THREE.Group | undefined, n: SavedVec3 | null | undefined): THREE.Vector3 | null {
  if (!group || !n) return null
  return savedToVec(n).transformDirection(group.matrixWorld).normalize()
}

function findMeshInModel(modelId: string, meshUuid: string): THREE.Mesh | null {
  const g = modelGroupsById.get(modelId)
  if (!g) return null
  let found: THREE.Mesh | null = null
  g.traverse((obj) => {
    if (found) return
    if (obj instanceof THREE.Mesh && obj.uuid === meshUuid) found = obj
  })
  return found
}

function meshPointToSaved(mesh: THREE.Mesh, worldPoint: THREE.Vector3): SavedVec3 {
  return vecToSaved(mesh.worldToLocal(worldPoint.clone()))
}

function meshNormalToSaved(mesh: THREE.Mesh, worldNormal: THREE.Vector3): SavedVec3 {
  const n = worldNormal.clone()
  const inv = mesh.matrixWorld.clone().invert()
  n.transformDirection(inv).normalize()
  return vecToSaved(n)
}

function pushMeasureAnchor(
  mesh: THREE.Mesh,
  modelId: string,
  worldPoint: THREE.Vector3,
  worldNormal: THREE.Vector3 | null,
) {
  measurementPoints.push(worldPoint.clone())
  measurementPointNormals.push(worldNormal?.clone() ?? null)
  measurementPointModelIds.push(modelId || null)
  measurementPointMeshUuids.push(mesh.uuid)
  measurementPointLocals.push(meshPointToSaved(mesh, worldPoint))
  measurementPointNormalLocals.push(worldNormal ? meshNormalToSaved(mesh, worldNormal) : null)
}

function setMeasureAnchorAt(
  index: number,
  mesh: THREE.Mesh,
  modelId: string,
  worldPoint: THREE.Vector3,
  worldNormal: THREE.Vector3 | null,
) {
  measurementPointModelIds[index] = modelId || null
  measurementPointMeshUuids[index] = mesh.uuid
  measurementPointLocals[index] = meshPointToSaved(mesh, worldPoint)
  measurementPointNormalLocals[index] = worldNormal ? meshNormalToSaved(mesh, worldNormal) : null
}

function resolveSavedPointWorld(
  modelId: string | null | undefined,
  local: SavedVec3 | null | undefined,
  worldFallback: SavedVec3,
  meshUuid?: string | null,
): THREE.Vector3 {
  if (modelId && meshUuid && local) {
    const mesh = findMeshInModel(modelId, meshUuid)
    if (mesh) return mesh.localToWorld(savedToVec(local))
  }
  if (modelId && local) {
    const g = modelGroupsById.get(modelId)
    if (g) return g.localToWorld(savedToVec(local))
  }
  return savedToVec(worldFallback)
}

function resolveSavedNormalWorld(
  modelId: string | null | undefined,
  nLocal: SavedVec3 | null | undefined,
  nWorld: SavedVec3 | null | undefined,
  meshUuid?: string | null,
): THREE.Vector3 | null {
  if (modelId && meshUuid && nLocal) {
    const mesh = findMeshInModel(modelId, meshUuid)
    if (mesh) return savedToVec(nLocal).transformDirection(mesh.matrixWorld).normalize()
  }
  if (modelId && nLocal) {
    return localNormalToWorld(modelGroupsById.get(modelId), nLocal)
  }
  return nWorld ? savedToVec(nWorld) : null
}

function refreshActiveMeasurementAnchors() {
  for (let i = 0; i < measurementPoints.length; i++) {
    const mid = measurementPointModelIds[i]
    const local = measurementPointLocals[i]
    if (!mid || !local) continue
    measurementPoints[i] = resolveSavedPointWorld(
      mid,
      local,
      vecToSaved(measurementPoints[i]),
      measurementPointMeshUuids[i],
    )
    const nLocal = measurementPointNormalLocals[i]
    if (nLocal) {
      const nw = resolveSavedNormalWorld(mid, nLocal, null, measurementPointMeshUuids[i])
      if (nw) measurementPointNormals[i] = nw
    }
  }
}

function projectPerpendicularByNormals(
  a: THREE.Vector3,
  b: THREE.Vector3,
  nA: THREE.Vector3 | null,
  nB: THREE.Vector3 | null,
): { basePoint: THREE.Vector3; otherPoint: THREE.Vector3; projected: THREE.Vector3; distanceMm: number } | null {
  if (!nA && !nB) return null
  const baseNormal = (nB ?? nA)!.clone().normalize()
  const basePoint = (nB ? b : a).clone()
  const otherPoint = (nB ? a : b).clone()
  const distSigned = otherPoint.clone().sub(basePoint).dot(baseNormal)
  const projected = otherPoint.clone().sub(baseNormal.clone().multiplyScalar(distSigned))
  return { basePoint, otherPoint, projected, distanceMm: Math.abs(distSigned) }
}

function saveDistanceMeasurement() {
  if (measurementPoints.length !== 2) return
  const [a, b] = measurementPoints
  const lengthMm = a.distanceTo(b)
  const id = `m_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
  const mid = a.clone().add(b).multiplyScalar(0.5)
  const anchorModelId = measurementPointModelIds[0] ?? measurementPointModelIds[1] ?? null
  const displayPlane = buildSavedDisplayPlaneFields(mid, anchorModelId)
  const row: SavedMeasurement = {
    id,
    type: 'distance',
    createdAt: new Date().toLocaleTimeString('ru-RU'),
    lengthMm,
    parallelMm: 0,
    trianglePerpMm: 0,
    surfacePerpMm: null,
    p1: vecToSaved(a),
    p2: vecToSaved(b),
    n1: measurementPointNormals[0] ? vecToSaved(measurementPointNormals[0]!) : null,
    n2: measurementPointNormals[1] ? vecToSaved(measurementPointNormals[1]!) : null,
    modelId1: measurementPointModelIds[0] ?? null,
    modelId2: measurementPointModelIds[1] ?? null,
    meshUuid1: measurementPointMeshUuids[0] ?? null,
    meshUuid2: measurementPointMeshUuids[1] ?? null,
    p1Local: measurementPointLocals[0] ?? null,
    p2Local: measurementPointLocals[1] ?? null,
    n1Local: measurementPointNormalLocals[0] ?? null,
    n2Local: measurementPointNormalLocals[1] ?? null,
    outputPlaneModelId: displayPlane.outputPlaneModelId,
    outputPlaneLocalPoint: displayPlane.outputPlaneLocalPoint,
    outputPlaneLocalNormal: displayPlane.outputPlaneLocalNormal,
    lineOffsetMm: defaultMeasurementLineOffsetMm(),
  }
  measurementHistory.value = [row, ...measurementHistory.value].slice(0, 200)
  selectedMeasurementId.value = null
  measurePreviewPoint = null
  measureStatusHint.value = `Размер ${row.lengthMm.toFixed(2)} мм сохранён. Потяните линию для выноса или кликните 1-ю точку.`
  rebuildSavedMeasurementsVisuals()
  measurementPoints = []
  measurementPointNormals = []
  measurementPointModelIds = []
  measurementPointMeshUuids = []
  measurementPointLocals = []
  measurementPointNormalLocals = []
  for (const g of measurementFaceGeometries) g.dispose()
  measurementFaceGeometries = []
  updateMeasurementGraphics()
  refreshMeasurementReferenceFaceHighlights()
}

function saveRadiusMeasurement(
  center: THREE.Vector3,
  radius: number,
  normal: THREE.Vector3,
  modelId: string | null,
  localCenter: SavedVec3 | null,
  localNormal: SavedVec3 | null,
  centerMeshUuid: string | null = null,
) {
  const id = `m_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
  const row: SavedMeasurement = {
    id,
    type: 'radius',
    createdAt: new Date().toLocaleTimeString('ru-RU'),
    lengthMm: radius,
    parallelMm: 0,
    trianglePerpMm: 0,
    surfacePerpMm: null,
    p1: vecToSaved(center),
    p2: vecToSaved(center),
    n1: vecToSaved(normal),
    n2: null,
    centerModelId: modelId,
    centerMeshUuid: centerMeshUuid,
    centerLocal: localCenter,
    centerNormalLocal: localNormal,
    radiusMmValue: radius,
  }
  measurementHistory.value = [row, ...measurementHistory.value].slice(0, 200)
  selectedMeasurementId.value = row.id
  rebuildSavedMeasurementsVisuals()
}

function saveDiameterMeasurement(
  firstCenter: THREE.Vector3,
  firstRadius: number,
  firstNormal: THREE.Vector3,
  firstModelId: string | null,
  firstCenterLocal: SavedVec3 | null,
  firstNormalLocal: SavedVec3 | null,
  secondCenter?: THREE.Vector3,
  secondModelId?: string | null,
  secondCenterLocal?: SavedVec3 | null,
  firstCenterMeshUuid: string | null = null,
  secondCenterMeshUuid: string | null = null,
) {
  const id = `m_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
  const p2 = secondCenter ?? firstCenter
  const row: SavedMeasurement = {
    id,
    type: 'diameter',
    createdAt: new Date().toLocaleTimeString('ru-RU'),
    lengthMm: firstRadius * 2,
    parallelMm: secondCenter ? firstCenter.distanceTo(secondCenter) : 0,
    trianglePerpMm: 0,
    surfacePerpMm: null,
    p1: vecToSaved(firstCenter),
    p2: vecToSaved(p2),
    n1: vecToSaved(firstNormal),
    n2: null,
    centerModelId: firstModelId,
    centerMeshUuid: firstCenterMeshUuid,
    centerLocal: firstCenterLocal,
    centerNormalLocal: firstNormalLocal,
    radiusMmValue: firstRadius,
    secondCenterModelId: secondModelId ?? null,
    secondCenterMeshUuid: secondCenterMeshUuid,
    secondCenterLocal: secondCenterLocal ?? null,
  }
  measurementHistory.value = [row, ...measurementHistory.value].slice(0, 200)
  selectedMeasurementId.value = row.id
  rebuildSavedMeasurementsVisuals()
}

function saveArcMeasurement(path: THREE.Vector3[], length: number, modelId: string | null, pathLocal: SavedVec3[] | null) {
  const id = `m_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
  const row: SavedMeasurement = {
    id,
    type: 'arc',
    createdAt: new Date().toLocaleTimeString('ru-RU'),
    lengthMm: length,
    parallelMm: 0,
    trianglePerpMm: 0,
    surfacePerpMm: null,
    p1: path.length ? vecToSaved(path[0]) : { x: 0, y: 0, z: 0 },
    p2: path.length ? vecToSaved(path[path.length - 1]) : { x: 0, y: 0, z: 0 },
    n1: null,
    n2: null,
    arcPath: path.map((p) => vecToSaved(p)),
    arcModelId: modelId,
    arcPathLocal: pathLocal,
    displayValue: length.toFixed(2),
  }
  measurementHistory.value = [row, ...measurementHistory.value].slice(0, 200)
  selectedMeasurementId.value = row.id
  rebuildSavedMeasurementsVisuals()
}

function saveCadLinearMeasurement(
  a: THREE.Vector3,
  b: THREE.Vector3,
  modelId1: string | null,
  modelId2: string | null,
  p1Local: SavedVec3 | null,
  p2Local: SavedVec3 | null,
  n1: THREE.Vector3 | null,
  n2: THREE.Vector3 | null,
  n1Local: SavedVec3 | null,
  n2Local: SavedVec3 | null,
  outputPlaneModelId: string | null,
  outputPlaneLocalPoint: SavedVec3 | null,
  outputPlaneLocalNormal: SavedVec3 | null,
  meshUuid1: string | null = null,
  meshUuid2: string | null = null,
) {
  let planePoint = outputPlaneLocalPoint ? savedToVec(outputPlaneLocalPoint) : (cadLinearPlanePoint ?? a.clone())
  let planeNormal = outputPlaneLocalNormal ? savedToVec(outputPlaneLocalNormal).normalize() : (cadLinearPlaneNormal ?? new THREE.Vector3(0, 1, 0))
  if (outputPlaneModelId) {
    const g = modelGroupsById.get(outputPlaneModelId)
    if (g) {
      planePoint = g.localToWorld(planePoint)
      planeNormal = localNormalToWorld(g, outputPlaneLocalNormal) ?? planeNormal
    }
  }
  const n = planeNormal.clone().normalize()
  const proj = (p: THREE.Vector3) => p.clone().sub(n.clone().multiplyScalar(p.clone().sub(planePoint).dot(n)))
  const aProj = proj(a)
  const bProj = proj(b)
  const perpByPlane = projectPerpendicularByNormals(
    a,
    b,
    n1,
    n2,
  )
  const len = perpByPlane ? perpByPlane.distanceMm : aProj.distanceTo(bProj)
  const id = `m_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
  const row: SavedMeasurement = {
    id,
    type: 'cad-linear',
    createdAt: new Date().toLocaleTimeString('ru-RU'),
    lengthMm: len,
    parallelMm: aProj.distanceTo(bProj),
    trianglePerpMm: Math.abs(a.clone().sub(aProj).dot(n) - b.clone().sub(bProj).dot(n)),
    surfacePerpMm: null,
    p1: vecToSaved(a),
    p2: vecToSaved(b),
    n1: n1 ? vecToSaved(n1) : null,
    n2: n2 ? vecToSaved(n2) : null,
    modelId1,
    modelId2,
    meshUuid1,
    meshUuid2,
    p1Local,
    p2Local,
    n1Local,
    n2Local,
    displayValue: len.toFixed(2),
    outputPlaneModelId,
    outputPlaneLocalPoint,
    outputPlaneLocalNormal,
    lineOffsetMm: defaultMeasurementLineOffsetMm(),
  }
  measurementHistory.value = [row, ...measurementHistory.value].slice(0, 200)
  selectedMeasurementId.value = row.id
  rebuildSavedMeasurementsVisuals()
}

function restoreMeasurement(row: SavedMeasurement, focusCamera = true) {
  selectedRemarkId.value = null
  measureModeRef.value = true
  clearMeasurements()
  if (row.type === 'radius') {
    const center = resolveSavedPointWorld(row.centerModelId, row.centerLocal, row.p1, row.centerMeshUuid)
    const normal =
      resolveSavedNormalWorld(row.centerModelId, row.centerNormalLocal, row.n1, row.centerMeshUuid)
      ?? new THREE.Vector3(0, 1, 0)
    radiusOrDiameterResult = {
      center,
      radius: row.radiusMmValue ?? row.lengthMm,
      normal,
      isDiameter: false,
    }
    measureTypeRef.value = 'radius'
    updateMeasurementGraphics()
    selectedMeasurementId.value = row.id
    if (focusCamera) {
      controls.target.copy(center)
      controls.update()
    }
    rebuildSavedMeasurementsVisuals()
    return
  }
  if (row.type === 'diameter') {
    const center = resolveSavedPointWorld(row.centerModelId, row.centerLocal, row.p1, row.centerMeshUuid)
    const normal =
      resolveSavedNormalWorld(row.centerModelId, row.centerNormalLocal, row.n1, row.centerMeshUuid)
      ?? new THREE.Vector3(0, 1, 0)
    firstClickHole = {
      center: center.clone(),
      radius: (row.radiusMmValue ?? row.lengthMm * 0.5),
      normal: normal.clone(),
    }
    radiusOrDiameterResult = {
      center: center.clone(),
      radius: row.radiusMmValue ?? row.lengthMm * 0.5,
      normal: normal.clone(),
      isDiameter: true,
    }
    if (row.secondCenterLocal || row.secondCenterModelId || row.p2) {
      const second = resolveSavedPointWorld(row.secondCenterModelId, row.secondCenterLocal, row.p2, row.secondCenterMeshUuid)
      secondHoleResult = { center: second.clone(), radius: row.radiusMmValue ?? row.lengthMm * 0.5, normal: normal.clone() }
      measurementPoints = [center.clone(), second.clone()]
      measurementPointNormals = [null, null]
    }
    measureTypeRef.value = 'diameter'
    updateMeasurementGraphics()
    selectedMeasurementId.value = row.id
    if (focusCamera) {
      controls.target.copy(center)
      controls.update()
    }
    rebuildSavedMeasurementsVisuals()
    return
  }
  if (row.type === 'arc') {
    let path: THREE.Vector3[] = []
    if (row.arcModelId && row.arcPathLocal?.length) {
      const g = modelGroupsById.get(row.arcModelId)
      if (g) path = row.arcPathLocal.map((p) => g.localToWorld(savedToVec(p)))
    }
    if (path.length === 0 && row.arcPath?.length) path = row.arcPath.map((p) => savedToVec(p))
    if (path.length >= 2) {
      arcResult = { path, length: row.lengthMm }
      measureTypeRef.value = 'arc'
      updateMeasurementGraphics()
      selectedMeasurementId.value = row.id
      if (focusCamera) {
        controls.target.copy(path[Math.floor(path.length * 0.5)])
        controls.update()
      }
      rebuildSavedMeasurementsVisuals()
    }
    return
  }
  if (row.type === 'cad-linear') {
    const a = resolveSavedPointWorld(row.modelId1, row.p1Local, row.p1, row.meshUuid1)
    const b = resolveSavedPointWorld(row.modelId2, row.p2Local, row.p2, row.meshUuid2)
    measurementPoints = [a, b]
    measurementPointNormals = [
      resolveSavedNormalWorld(row.modelId1, row.n1Local, row.n1, row.meshUuid1),
      resolveSavedNormalWorld(row.modelId2, row.n2Local, row.n2, row.meshUuid2),
    ]
    if (row.outputPlaneModelId && row.outputPlaneLocalPoint && row.outputPlaneLocalNormal) {
      const g = modelGroupsById.get(row.outputPlaneModelId)
      if (g) {
        cadLinearPlanePoint = g.localToWorld(savedToVec(row.outputPlaneLocalPoint))
        cadLinearPlaneNormal = localNormalToWorld(g, row.outputPlaneLocalNormal)
      }
    }
    measureTypeRef.value = 'cad-linear'
    selectedMeasurementId.value = row.id
    if (focusCamera) {
      controls.target.copy(a.clone().add(b).multiplyScalar(0.5))
      controls.update()
    }
    rebuildSavedMeasurementsVisuals()
    refreshMeasurementReferenceFaceHighlights()
    return
  }
  if (row.type !== 'distance') return
  measureTypeRef.value = 'distance'
  selectedMeasurementId.value = row.id
  if (focusCamera) {
    const a = resolveSavedPointWorld(row.modelId1, row.p1Local, row.p1, row.meshUuid1)
    const b = resolveSavedPointWorld(row.modelId2, row.p2Local, row.p2, row.meshUuid2)
    controls.target.copy(a.clone().add(b).multiplyScalar(0.5))
    controls.update()
  }
  rebuildSavedMeasurementsVisuals()
  refreshMeasurementReferenceFaceHighlights()
}

function clearMeasurementHistory() {
  measurementHistory.value = []
  selectedMeasurementId.value = null
  clearSavedMeasurementLabelElements()
  rebuildSavedMeasurementsVisuals()
}

function refreshSelectedMeasurementAfterTransform() {
  if (!selectedMeasurementId.value) return
  const row = measurementHistory.value.find((m) => m.id === selectedMeasurementId.value)
  if (!row) return
  restoreMeasurement(row, false)
  rebuildSavedMeasurementsVisuals()
}

function clearSavedMeasurementVisuals() {
  if (!savedMeasurementsGroup) return
  while (savedMeasurementsGroup.children.length > 0) {
    const c = savedMeasurementsGroup.children[0]
    savedMeasurementsGroup.remove(c)
    if ('geometry' in c && c.geometry) c.geometry.dispose()
    if ('material' in c && c.material) {
      const m = c.material as THREE.Material | THREE.Material[]
      if (Array.isArray(m)) m.forEach((x) => x.dispose())
      else m.dispose()
    }
    const sprite = c as THREE.Sprite
    if (sprite.material && 'map' in sprite.material) {
      const map = (sprite.material as THREE.SpriteMaterial).map
      map?.dispose()
    }
  }
}

function createMeasurementTextSprite(text: string, color = '#eaf2ff'): THREE.Sprite {
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')!
  const fontSize = 32
  ctx.font = `600 ${fontSize}px Arial`
  const w = Math.max(64, Math.ceil(ctx.measureText(text).width + 24))
  const h = 52
  canvas.width = w
  canvas.height = h
  ctx.font = `600 ${fontSize}px Arial`
  ctx.fillStyle = 'rgba(20,28,44,0.84)'
  ctx.fillRect(0, 0, w, h)
  ctx.strokeStyle = 'rgba(130,160,220,0.85)'
  ctx.strokeRect(0.5, 0.5, w - 1, h - 1)
  ctx.fillStyle = color
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, w / 2, h / 2 + 1)
  const tex = new THREE.CanvasTexture(canvas)
  tex.minFilter = THREE.LinearFilter
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, depthTest: true })
  const sprite = new THREE.Sprite(mat)
  const scale = Math.max(4, dimFontSizeMm.value)
  sprite.scale.set(scale * 1.85, scale, 1)
  return sprite
}

function adaptiveMeasurementScale(_worldPoint: THREE.Vector3): number {
  const base = Math.max(4, dimFontSizeMm.value)
  const targetH = Math.max(loadedSceneCharDim * 0.014, 0.35)
  return Math.max(0.2, Math.min(1.4, targetH / base))
}

function orientOffsetDirForScreen(dir: THREE.Vector3, anchor: THREE.Vector3): THREE.Vector3 {
  if (!camera) return dir
  const p = anchor.clone().project(camera)
  const q = anchor.clone().add(dir).project(camera)
  // Положительный вынос всегда в "экранный верх", чтобы drag не инвертировался.
  return q.y >= p.y ? dir : dir.clone().negate()
}

function normalizeSignedOffset(offset: number): number {
  const sign = Math.sign(offset) || 1
  return sign * Math.max(2, Math.abs(offset))
}

function addLine(group: THREE.Group, a: THREE.Vector3, b: THREE.Vector3, color = 0x7fc2ff, measurementId?: string): void {
  const g = new THREE.BufferGeometry().setFromPoints([a, b])
  const m = new THREE.LineBasicMaterial({ color })
  const line = new THREE.Line(g, m)
  if (measurementId) line.userData.measurementId = measurementId
  group.add(line)
}

function addDimLine(
  group: THREE.Group,
  a: THREE.Vector3,
  b: THREE.Vector3,
  color = DIM_GOST_COLOR,
  measurementId?: string,
): void {
  const g = new THREE.BufferGeometry().setFromPoints([a, b])
  const m = new THREE.LineBasicMaterial({
    color,
    depthTest: false,
    transparent: true,
    opacity: 0.96,
  })
  const line = new THREE.Line(g, m)
  line.renderOrder = 1000
  if (measurementId) line.userData.measurementId = measurementId
  group.add(line)
}

function addArrowHead(group: THREE.Group, tip: THREE.Vector3, dirToInside: THREE.Vector3, color = 0x7fc2ff, size = 4, measurementId?: string): void {
  const u = dirToInside.clone().normalize()
  const aux = Math.abs(u.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0)
  const v = new THREE.Vector3().crossVectors(u, aux).normalize()
  const b = tip.clone().add(u.clone().multiplyScalar(size))
  addLine(group, tip, b.clone().add(v.clone().multiplyScalar(size * 0.45)), color, measurementId)
  addLine(group, tip, b.clone().add(v.clone().multiplyScalar(-size * 0.45)), color, measurementId)
}

const DIM_GOST_COLOR = 0xffad5b
/** Мягкая подсветка 1-й опорной грани / точки */
const MEASURE_REF_FACE_COLOR_1 = 0x8eedb8
/** Мягкая подсветка 2-й опорной грани / точки */
const MEASURE_REF_FACE_COLOR_2 = 0xf0a0a0
const MEASURE_REF_FACE_OPACITY = 0.815

function measurementHighlightLiftMm(): number {
  return Math.max(0.12, loadedSceneCharDim * 4e-5)
}

/** Слегка отодвигает геометрию от поверхности модели — убирает z-fighting и «мерцание пикселей». */
function liftHighlightGeometryFromSurface(geom: THREE.BufferGeometry, liftMm?: number): THREE.BufferGeometry {
  const g = geom.clone()
  const lift = liftMm ?? measurementHighlightLiftMm()
  if (!g.getAttribute('normal')) g.computeVertexNormals()
  const pos = g.getAttribute('position') as THREE.BufferAttribute
  const norm = g.getAttribute('normal') as THREE.BufferAttribute
  for (let i = 0; i < pos.count; i++) {
    pos.setXYZ(
      i,
      pos.getX(i) + norm.getX(i) * lift,
      pos.getY(i) + norm.getY(i) * lift,
      pos.getZ(i) + norm.getZ(i) * lift,
    )
  }
  pos.needsUpdate = true
  return g
}

function clearMeasurementPlanesGroup() {
  if (!measurementPlanesGroup) return
  while (measurementPlanesGroup.children.length) {
    const c = measurementPlanesGroup.children[0]
    measurementPlanesGroup.remove(c)
    if ('geometry' in c && c.geometry) c.geometry.dispose()
    if ('material' in c && c.material) {
      const m = c.material as THREE.Material | THREE.Material[]
      if (Array.isArray(m)) m.forEach((x) => x.dispose())
      else m.dispose()
    }
  }
}

function addMeasurementFaceHighlightMesh(geom: THREE.BufferGeometry, color: number, opacity = MEASURE_REF_FACE_OPACITY) {
  if (!measurementPlanesGroup) return
  const mat = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity,
    side: THREE.DoubleSide,
    depthWrite: false,
    depthTest: true,
    polygonOffset: true,
    polygonOffsetFactor: -4,
    polygonOffsetUnits: -4,
  })
  const mesh = new THREE.Mesh(liftHighlightGeometryFromSurface(geom), mat)
  mesh.renderOrder = 1003
  measurementPlanesGroup.add(mesh)
}

function buildFaceHighlightGeometryFromHit(hit: THREE.Intersection): THREE.BufferGeometry | null {
  const mesh = hit.object as THREE.Mesh
  const face = hit.face
  if (!face) return buildWorldFaceTriangleFromHit(hit)
  const faceIndex =
    typeof (hit as THREE.Intersection & { faceIndex?: number }).faceIndex === 'number'
      ? (hit as THREE.Intersection & { faceIndex: number }).faceIndex
      : Math.floor(face.a / 3)
  const coplanar = getCoplanarFaceGeometry(mesh, faceIndex)
  if (coplanar) {
    const g = coplanar.clone()
    g.applyMatrix4(mesh.matrixWorld)
    return g
  }
  return buildWorldFaceTriangleFromHit(hit)
}

function findFaceIndexNearSavedAnchor(
  mesh: THREE.Mesh,
  worldPoint: THREE.Vector3,
  worldNormal: THREE.Vector3 | null,
): number | null {
  const geom = mesh.geometry as THREE.BufferGeometry
  const pos = geom.attributes.position as THREE.BufferAttribute | undefined
  if (!pos) return null
  const index = geom.index
  const triCount = index ? index.count / 3 : pos.count / 3
  const inv = mesh.matrixWorld.clone().invert()
  const localPt = worldPoint.clone().applyMatrix4(inv)
  let bestFi: number | null = null
  let bestScore = Infinity
  for (let fi = 0; fi < triCount; fi++) {
    const nw = meshTriangleWorldNormal(mesh, fi)
    if (!nw) continue
    if (worldNormal && nw.dot(worldNormal) < 0.85) continue
    const ia = index ? index.getX(fi * 3) : fi * 3
    const ib = index ? index.getX(fi * 3 + 1) : fi * 3 + 1
    const ic = index ? index.getX(fi * 3 + 2) : fi * 3 + 2
    const cx = (pos.getX(ia) + pos.getX(ib) + pos.getX(ic)) / 3
    const cy = (pos.getY(ia) + pos.getY(ib) + pos.getY(ic)) / 3
    const cz = (pos.getZ(ia) + pos.getZ(ib) + pos.getZ(ic)) / 3
    const distSq = localPt.distanceToSquared(new THREE.Vector3(cx, cy, cz))
    if (distSq < bestScore) {
      bestScore = distSq
      bestFi = fi
    }
  }
  return bestFi
}

function buildSavedAnchorFaceHighlight(row: SavedMeasurement, slot: 0 | 1): THREE.BufferGeometry | null {
  const modelId = slot === 0 ? row.modelId1 : row.modelId2
  const meshUuid = slot === 0 ? row.meshUuid1 : row.meshUuid2
  const localPoint = slot === 0 ? row.p1Local : row.p2Local
  const worldFallback = slot === 0 ? row.p1 : row.p2
  const nLocal = slot === 0 ? row.n1Local : row.n2Local
  const nWorld = slot === 0 ? row.n1 : row.n2
  if (!modelId || !meshUuid) return null
  const mesh = findMeshInModel(modelId, meshUuid)
  if (!mesh) return null
  const worldPoint = resolveSavedPointWorld(modelId, localPoint, worldFallback, meshUuid)
  const worldNormal = resolveSavedNormalWorld(modelId, nLocal, nWorld, meshUuid)
  const faceIndex = findFaceIndexNearSavedAnchor(mesh, worldPoint, worldNormal)
  if (faceIndex == null) return null
  return getCoplanarFaceGeometry(mesh, faceIndex)
}

function refreshMeasurementReferenceFaceHighlights() {
  clearMeasurementPlanesGroup()
  const colors = [MEASURE_REF_FACE_COLOR_1, MEASURE_REF_FACE_COLOR_2] as const
  const activeSlotGeom: (THREE.BufferGeometry | null)[] = [null, null]

  if (measureModeRef.value && measureTypeRef.value === 'cad-linear') {
    if (cadLinearPlane1.value?.previewGeometry) activeSlotGeom[0] = cadLinearPlane1.value.previewGeometry
    if (cadLinearPlane2.value?.previewGeometry) activeSlotGeom[1] = cadLinearPlane2.value.previewGeometry
  } else if (measureModeRef.value && measureTypeRef.value === 'distance') {
    const count = Math.min(measurementFaceGeometries.length, measurementPoints.length, 2)
    for (let i = 0; i < count; i++) activeSlotGeom[i] = measurementFaceGeometries[i]
  }

  const savedRow = selectedMeasurementId.value
    ? measurementHistory.value.find((m) => m.id === selectedMeasurementId.value) ?? null
    : null
  const linearSavedRow =
    savedRow && (savedRow.type === 'distance' || savedRow.type === 'cad-linear') ? savedRow : null

  for (let slot = 0; slot < 2; slot++) {
    let geom: THREE.BufferGeometry | null = activeSlotGeom[slot]
    if (!geom && linearSavedRow) geom = buildSavedAnchorFaceHighlight(linearSavedRow, slot as 0 | 1)
    if (!geom) continue
    addMeasurementFaceHighlightMesh(geom.clone(), colors[slot])
  }
}

function addGostArrowHead(
  group: THREE.Object3D,
  tip: THREE.Vector3,
  dirToInside: THREE.Vector3,
  color = DIM_GOST_COLOR,
  size = 4,
  measurementId?: string,
): void {
  const u = dirToInside.clone().normalize()
  const aux = Math.abs(u.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0)
  const v = new THREE.Vector3().crossVectors(u, aux).normalize()
  const h = size * 0.55
  const halfW = size * 0.22
  const base = tip.clone().add(u.clone().multiplyScalar(h))
  const p1 = base.clone().add(v.clone().multiplyScalar(halfW))
  const p2 = base.clone().add(v.clone().multiplyScalar(-halfW))
  const geom = new THREE.BufferGeometry()
  geom.setAttribute(
    'position',
    new THREE.Float32BufferAttribute(
      new Float32Array([tip.x, tip.y, tip.z, p1.x, p1.y, p1.z, p2.x, p2.y, p2.z]),
      3,
    ),
  )
  const mesh = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide }))
  if (measurementId) mesh.userData.measurementId = measurementId
  group.add(mesh)
}

function rebuildSavedMeasurementsVisuals() {
  if (!savedMeasurementsGroup) return
  clearSavedMeasurementVisuals()
  for (const row of measurementHistory.value) {
    if (row.type === 'distance') {
      const dim = resolveLinearDimForDistanceRow(row)
      if (!dim) continue
      const scale = adaptiveMeasurementScale(dim.labelWorld)
      const arrow = Math.max(3, dimArrowSizeMm.value * scale)
      addDimLine(savedMeasurementsGroup, dim.srcA, dim.dimA, DIM_GOST_COLOR, row.id)
      addDimLine(savedMeasurementsGroup, dim.srcB, dim.dimB, DIM_GOST_COLOR, row.id)
      addDimLine(savedMeasurementsGroup, dim.dimA, dim.dimB, DIM_GOST_COLOR, row.id)
      addGostArrowHead(savedMeasurementsGroup, dim.dimA, dim.dimB.clone().sub(dim.dimA), DIM_GOST_COLOR, arrow, row.id)
      addGostArrowHead(savedMeasurementsGroup, dim.dimB, dim.dimA.clone().sub(dim.dimB), DIM_GOST_COLOR, arrow, row.id)
      continue
    }
    if (row.type === 'radius' || row.type === 'diameter') {
      const center = resolveSavedPointWorld(row.centerModelId, row.centerLocal, row.p1, row.centerMeshUuid)
      const radius = row.radiusMmValue ?? (row.type === 'diameter' ? row.lengthMm * 0.5 : row.lengthMm)
      const normal =
        resolveSavedNormalWorld(row.centerModelId, row.centerNormalLocal, row.n1, row.centerMeshUuid)
        ?? new THREE.Vector3(0, 1, 0)
      const u = new THREE.Vector3().crossVectors(normal, new THREE.Vector3(1, 0, 0)).normalize()
      if (u.lengthSq() < 0.01) u.crossVectors(normal, new THREE.Vector3(0, 1, 0)).normalize()
      const rim = center.clone().add(u.clone().multiplyScalar(radius))
      const color = row.type === 'diameter' ? 0xffb35f : 0x73e6a6
      const scale = adaptiveMeasurementScale(center)
      const arrow = Math.max(3, dimArrowSizeMm.value * scale)
      addLine(savedMeasurementsGroup, center, rim, color, row.id)
      addArrowHead(savedMeasurementsGroup, rim, center.clone().sub(rim), color, arrow, row.id)
      if (row.type === 'diameter') {
        const rim2 = center.clone().add(u.clone().multiplyScalar(-radius))
        addLine(savedMeasurementsGroup, rim, rim2, color, row.id)
        addArrowHead(savedMeasurementsGroup, rim, rim2.clone().sub(rim), color, arrow, row.id)
        addArrowHead(savedMeasurementsGroup, rim2, rim.clone().sub(rim2), color, arrow, row.id)
      }
      const t = createMeasurementTextSprite(row.type === 'diameter' ? `⌀${measurementValueText(row)}` : `R${measurementValueText(row)}`)
      t.scale.multiplyScalar(scale)
      t.userData.measurementId = row.id
      t.position.copy(center.clone().add(u.clone().multiplyScalar(radius * 0.55)))
      savedMeasurementsGroup.add(t)
      continue
    }
    if (row.type === 'arc') {
      let path: THREE.Vector3[] = []
      if (row.arcModelId && row.arcPathLocal?.length) {
        const g = modelGroupsById.get(row.arcModelId)
        if (g) path = row.arcPathLocal.map((p) => g.localToWorld(savedToVec(p)))
      }
      if (path.length === 0 && row.arcPath?.length) path = row.arcPath.map((p) => savedToVec(p))
      if (path.length >= 2) {
        const geom = new THREE.BufferGeometry().setFromPoints(path)
        const arcLine = new THREE.Line(geom, new THREE.LineBasicMaterial({ color: 0xffaa55 }))
        arcLine.userData.measurementId = row.id
        savedMeasurementsGroup.add(arcLine)
        const p0 = path[0]
        const p1 = path[path.length - 1]
        const scale = adaptiveMeasurementScale(path[Math.floor(path.length * 0.5)])
        const arrow = Math.max(3, dimArrowSizeMm.value * scale)
        addArrowHead(savedMeasurementsGroup, p0, path[1].clone().sub(p0), 0xffaa55, arrow, row.id)
        addArrowHead(savedMeasurementsGroup, p1, path[path.length - 2].clone().sub(p1), 0xffaa55, arrow, row.id)
        const mid = path[Math.floor(path.length * 0.5)].clone()
        const t = createMeasurementTextSprite(`⌒${measurementValueText(row)}`)
        t.scale.multiplyScalar(scale)
        t.userData.measurementId = row.id
        t.position.copy(mid)
        savedMeasurementsGroup.add(t)
      }
      continue
    }
    if (row.type === 'cad-linear') {
      const dim = resolveLinearDimForCadLinearRow(row)
      if (!dim) continue
      const scale = adaptiveMeasurementScale(dim.labelWorld)
      const arrow = Math.max(3, dimArrowSizeMm.value * scale)
      addDimLine(savedMeasurementsGroup, dim.srcA, dim.dimA, DIM_GOST_COLOR, row.id)
      addDimLine(savedMeasurementsGroup, dim.srcB, dim.dimB, DIM_GOST_COLOR, row.id)
      addDimLine(savedMeasurementsGroup, dim.dimA, dim.dimB, DIM_GOST_COLOR, row.id)
      addGostArrowHead(savedMeasurementsGroup, dim.dimA, dim.dimB.clone().sub(dim.dimA), DIM_GOST_COLOR, arrow, row.id)
      addGostArrowHead(savedMeasurementsGroup, dim.dimB, dim.dimA.clone().sub(dim.dimB), DIM_GOST_COLOR, arrow, row.id)
    }
  }
  syncSavedMeasurementLabelElements()
  updateSavedMeasurementLabelPositions()
}

function removeMeasurement(id: string) {
  measurementHistory.value = measurementHistory.value.filter((m) => m.id !== id)
  if (selectedMeasurementId.value === id) {
    selectedMeasurementId.value = null
  }
  rebuildSavedMeasurementsVisuals()
  refreshMeasurementReferenceFaceHighlights()
}

function measurementTypeLabel(m: SavedMeasurement): string {
  if (m.type === 'cad-linear') return 'Лин.'
  return 'Изм.'
}

function measurementValueText(m: SavedMeasurement): string {
  return m.displayValue ?? m.lengthMm.toFixed(2)
}

const SNAP_SCREEN_THRESHOLD_SURFACE = 0.09
const SNAP_SCREEN_THRESHOLD_EDGE = 0.14
const SNAP_SCREEN_THRESHOLD_VERTEX = 0.16
const snapProj = new THREE.Vector3()
const snapSeg = new THREE.Line3()
const snapClosest = new THREE.Vector3()

type SnapCandidate = { point: THREE.Vector3; kind: 'vertex' | 'edge' | 'face' | 'surface' }

function updateGroundGrid(box?: THREE.Box3) {
  if (!scene) return
  if (groundGrid) {
    scene.remove(groundGrid)
    groundGrid.geometry.dispose()
    const mat = groundGrid.material
    if (Array.isArray(mat)) mat.forEach((m) => m.dispose())
    else mat.dispose()
    groundGrid = null
  }
  if (!showGroundGrid.value) return

  const refBox = box ?? getReferenceSceneBox()
  if (!refBox) return
  const sizeVec = refBox.getSize(new THREE.Vector3())
  const maxDim = Math.max(sizeVec.x, sizeVec.y, sizeVec.z, 1)
  const center = refBox.getCenter(new THREE.Vector3())
  const gridSize = Math.min(Math.max(2000, maxDim * 2.2), 50000)
  const step = Math.max(200, Math.round(gridSize / 40 / 100) * 100)
  const divisions = Math.min(60, Math.max(8, Math.round(gridSize / step)))
  const y = refBox.min.y
  groundGrid = new THREE.GridHelper(gridSize, divisions, 0x9aa7bb, 0xd7dee8)
  groundGrid.position.set(center.x, y, center.z)
  ;(groundGrid.material as THREE.Material).transparent = true
  ;(groundGrid.material as THREE.Material).opacity = 0.45
  scene.add(groundGrid)
}

function updateKeyLightShadowCamera(box?: THREE.Box3) {
  if (!keyLight) return
  const cam = keyLight.shadow.camera as THREE.OrthographicCamera
  let b: THREE.Box3 | null = null
  if (box && !box.isEmpty()) b = box
  else if (meshGroup && meshGroup.children.length > 0) {
    const tmp = new THREE.Box3().setFromObject(meshGroup)
    if (!tmp.isEmpty()) b = tmp
  }
  if (!b) return
  const center = b.getCenter(new THREE.Vector3())
  const size = b.getSize(new THREE.Vector3())
  keyLight.target.position.copy(center)
  keyLight.target.updateMatrixWorld(true)
  const maxDim = Math.max(size.x, size.y, size.z, 80)
  const half = maxDim * 0.85
  cam.left = -half
  cam.right = half
  cam.top = half
  cam.bottom = -half
  cam.near = Math.max(1, maxDim * 0.02)
  cam.far = Math.max(maxDim * 24, 5000)
  cam.updateProjectionMatrix()
}

function updateSceneLighting(box?: THREE.Box3) {
  const sizeVec = box ? box.getSize(new THREE.Vector3()) : new THREE.Vector3(2000, 2000, 2000)
  const center = box ? box.getCenter(new THREE.Vector3()) : new THREE.Vector3()
  const scale = Math.max(sizeVec.x, sizeVec.y, sizeVec.z, 200)
  if (keyLight) keyLight.position.set(center.x + scale * 0.9, center.y + scale * 1.25, center.z + scale * 0.8)
  if (fillLightA) fillLightA.position.set(center.x - scale * 0.8, center.y + scale * 0.75, center.z + scale * 0.6)
  if (fillLightB) fillLightB.position.set(center.x + scale * 0.65, center.y + scale * 0.6, center.z - scale * 0.95)
  if (fillLightC) fillLightC.position.set(center.x - scale * 0.7, center.y + scale * 0.5, center.z - scale * 0.8)
  if (rimLightA) rimLightA.position.set(center.x - scale * 1.1, center.y + scale * 0.9, center.z - scale * 1.2)
  if (rimLightB) rimLightB.position.set(center.x + scale * 1.15, center.y + scale * 0.4, center.z - scale * 1.05)
  updateKeyLightShadowCamera(box)
}

function toggleGroundGrid() {
  showGroundGrid.value = !showGroundGrid.value
  if (!showGroundGrid.value) {
    updateGroundGrid()
    return
  }
  const hasModels = meshGroup && meshGroup.children.length > 0
  const box = hasModels ? new THREE.Box3().setFromObject(meshGroup) : undefined
  updateGroundGrid(box)
}

function initScene() {
  if (!containerRef.value) return

  scene = new THREE.Scene()
  scene.background = new THREE.Color(sceneBackgroundHex.value)

  camera = new THREE.PerspectiveCamera(
    50,
    containerRef.value.clientWidth / containerRef.value.clientHeight,
    0.1,
    500000
  )
  camera.position.set(500, 400, 500)

  renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true, logarithmicDepthBuffer: true })
  renderer.setSize(containerRef.value.clientWidth, containerRef.value.clientHeight)
  idlePixelRatio = Math.min(window.devicePixelRatio, 2)
  renderer.setPixelRatio(idlePixelRatio)
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1
  renderer.localClippingEnabled = true
  renderer.shadowMap.enabled = false
  containerRef.value.appendChild(renderer.domElement)

  controls = new TrackballControls(camera, renderer.domElement)
  controls.zoomSpeed = 0.9
  controls.staticMoving = false
  controls.noZoom = true
  controls.target.set(0, 0, 0)
  controls.mouseButtons = {
    LEFT: -1,
    MIDDLE: THREE.MOUSE.PAN,
    RIGHT: THREE.MOUSE.ROTATE,
  }
  controls.addEventListener('start', onControlsStart)
  controls.addEventListener('end', onControlsEnd)
  applyMouseSettings()
  controls.handleResize()
  savedCameraPosition.copy(camera.position)
  savedCameraTarget.copy(controls.target)

  ambientLight = new THREE.AmbientLight(0xffffff, 0.38)
  scene.add(ambientLight)
  hemiLight = new THREE.HemisphereLight(0xffffff, 0xe9edf7, 0.45)
  scene.add(hemiLight)
  keyLight = new THREE.DirectionalLight(0xffffff, 0.42)
  keyLight.castShadow = false
  fillLightA = new THREE.DirectionalLight(0xffffff, 0.3)
  fillLightB = new THREE.DirectionalLight(0xffffff, 0.24)
  fillLightC = new THREE.DirectionalLight(0xffffff, 0.2)
  rimLightA = new THREE.DirectionalLight(0xffffff, 0.14)
  rimLightB = new THREE.DirectionalLight(0xffffff, 0.1)
  fillLightA.castShadow = false
  fillLightB.castShadow = false
  fillLightC.castShadow = false
  rimLightA.castShadow = false
  rimLightB.castShadow = false
  scene.add(keyLight, fillLightA, fillLightB, fillLightC, rimLightA, rimLightB)
  scene.add(keyLight.target)
  applySceneLightingForShadingMode()

  meshGroup = new THREE.Group()
  scene.add(meshGroup)
  hiddenOutlineGroup = new THREE.Group()
  scene.add(hiddenOutlineGroup)
  partFocusEdgeGroup = new THREE.Group()
  partFocusEdgeGroup.name = 'partFocusEdges'
  scene.add(partFocusEdgeGroup)
  overlayGroup = new THREE.Group()
  overlayGroup.visible = overlayEnabled.value
  scene.add(overlayGroup)

  measureGroup = new THREE.Group()
  scene.add(measureGroup)
  highlightGroup = new THREE.Group()
  scene.add(highlightGroup)
  measurementPlanesGroup = new THREE.Group()
  scene.add(measurementPlanesGroup)
  savedMeasurementsGroup = new THREE.Group()
  scene.add(savedMeasurementsGroup)
  assemblyHighlightGroup = new THREE.Group()
  scene.add(assemblyHighlightGroup)
  remarkAnchorsGroup = new THREE.Group()
  scene.add(remarkAnchorsGroup)

  updateSceneLighting()

  const axesSize = 100
  axesHelper = new THREE.Group()
  const axes = new THREE.AxesHelper(axesSize)
  axesHelper.add(axes)
  scene.add(axesHelper)
  syncWorldCoordSystemGroup()
  updateGroundGrid()

  raycaster = new THREE.Raycaster()
  mouse = new THREE.Vector2()
  measurementLabelEl = document.createElement('div')
  measurementLabelEl.className = 'measurement-label'
  measurementLabelEl.style.cssText =
    'position:absolute;pointer-events:none;color:#fff;background:rgba(0,0,0,0.75);padding:2px 8px;border-radius:4px;font-size:12px;white-space:nowrap;display:none;'
  containerRef.value.appendChild(measurementLabelEl)
  const labelStyle = 'position:absolute;pointer-events:none;color:#fff;background:rgba(0,0,0,0.75);padding:2px 8px;border-radius:4px;font-size:12px;white-space:nowrap;display:none;'
  measurementLabelEl0 = document.createElement('div')
  measurementLabelEl0.className = 'measurement-label'
  measurementLabelEl0.style.cssText = labelStyle
  containerRef.value.appendChild(measurementLabelEl0)
  measurementLabelEl1 = document.createElement('div')
  measurementLabelEl1.className = 'measurement-label'
  measurementLabelEl1.style.cssText = labelStyle
  containerRef.value.appendChild(measurementLabelEl1)
  measurementLabelEl2 = document.createElement('div')
  measurementLabelEl2.className = 'measurement-label'
  measurementLabelEl2.style.cssText = labelStyle
  containerRef.value.appendChild(measurementLabelEl2)
  measurementPerpLabelEl = document.createElement('div')
  measurementPerpLabelEl.className = 'measurement-label'
  measurementPerpLabelEl.style.cssText = labelStyle
  measurementPerpLabelEl.style.fontSize = '16px'
  containerRef.value.appendChild(measurementPerpLabelEl)
  measurementExtraLabelEl = document.createElement('div')
  measurementExtraLabelEl.className = 'measurement-label'
  measurementExtraLabelEl.style.cssText = labelStyle
  measurementExtraLabelEl.style.fontSize = '14px'
  containerRef.value.appendChild(measurementExtraLabelEl)
  diameterSecondLabelEl = document.createElement('div')
  diameterSecondLabelEl.className = 'measurement-label'
  diameterSecondLabelEl.style.cssText = labelStyle
  diameterSecondLabelEl.style.fontSize = '14px'
  containerRef.value.appendChild(diameterSecondLabelEl)
  hoverTooltipEl = document.createElement('div')
  hoverTooltipEl.className = 'measurement-label'
  hoverTooltipEl.style.cssText = labelStyle + 'font-size:11px;'
  hoverTooltipEl.style.display = 'none'
  containerRef.value.appendChild(hoverTooltipEl)
  savedMeasurementLabelsLayer = document.createElement('div')
  savedMeasurementLabelsLayer.className = 'saved-measurement-labels-layer'
  savedMeasurementLabelsLayer.style.cssText = 'position:absolute;inset:0;pointer-events:none;overflow:hidden;z-index:5;'
  containerRef.value.appendChild(savedMeasurementLabelsLayer)
  renderer.domElement.addEventListener('click', onCanvasClick)
  renderer.domElement.addEventListener('pointerdown', onCanvasPointerDownCapture, true)
  renderer.domElement.addEventListener('mousedown', onCanvasMouseDown, true)
  renderer.domElement.addEventListener('contextmenu', onCanvasContextMenu)
  renderer.domElement.addEventListener('mousemove', onCanvasMouseMove, false)
  renderer.domElement.addEventListener('mousemove', onCanvasMouseMovePan, true)
  renderer.domElement.addEventListener('mouseup', onCanvasMouseUp, true)
  window.addEventListener('mouseup', onCanvasMouseUp, true)
  renderer.domElement.addEventListener('wheel', onCanvasWheel, { passive: false })
  if (containerRef.value) {
    containerRef.value.addEventListener('mousemove', onContainerMouseMove, false)
  }

  function animate() {
    animationId = requestAnimationFrame(animate)
    controls.update()
    updateRemarkViewAngle()
    let hits: THREE.Intersection[] = []
    if (measureModeRef.value && meshGroup.children.length && containerRef.value) {
      const now = performance.now()
      const shouldUpdateHover = !isCameraInteracting && (hoverDirty || now - lastHoverUpdateAt >= HOVER_UPDATE_INTERVAL_MS)
      if (shouldUpdateHover) {
        const rect = renderer.domElement.getBoundingClientRect()
        raycaster.setFromCamera(mouse, camera)
        hits = intersectPickableMeshes(raycaster)
        while (highlightGroup.children.length) {
          const c = highlightGroup.children[0]
          highlightGroup.remove(c)
          if ('geometry' in c && c.geometry) c.geometry.dispose()
          if ('material' in c && c.material) (c.material as THREE.Material).dispose()
        }
        const hoverHit = pickSolidSurfaceHit(hits)
        if (hoverHit) {
        const hit = hoverHit
        const mesh = hit.object as THREE.Mesh
        const face = hit.face!
        const pos = mesh.geometry.attributes.position
        if (pos) {
          const faceIndex = typeof (hit as THREE.Intersection & { faceIndex?: number }).faceIndex === 'number'
            ? (hit as THREE.Intersection & { faceIndex: number }).faceIndex
            : Math.floor(face.a / 3)
          const worldNormal = hit.face!.normal.clone().transformDirection(mesh.matrixWorld).normalize()
          lastHoverNormal = worldNormal.clone()
          lastHoverPoint = hit.point.clone()
          // Для distance-режима исключаем тяжёлую цилиндрическую аналитику (миллионы граней).
          const needsHoleAnalysis =
            measureTypeRef.value === 'radius' || measureTypeRef.value === 'diameter' || measureTypeRef.value === 'hole-center-distance'
          const skipHeavyHover = draggedModelGroup !== null
          let holeInfo: { center: THREE.Vector3; radius: number; normal: THREE.Vector3 } | null = null
          let radiusInfo: { center: THREE.Vector3; radius: number } | null = null
          if (needsHoleAnalysis && !skipHeavyHover) {
            holeInfo = getHoverHoleInfo(mesh, hit.point)
            radiusInfo = holeInfo ? null : getHoverRadiusInfo(mesh, faceIndex, worldNormal)
            if (!holeInfo && radiusInfo && isCylinderAHole(mesh, radiusInfo.center, radiusInfo.radius, worldNormal, raycaster)) {
              holeInfo = { center: radiusInfo.center.clone(), radius: radiusInfo.radius, normal: worldNormal.clone() }
              radiusInfo = null
            }
          }
          // 1) Подсветка поверхности под курсором. Дорогую зону считаем только для режимов отверстий.
          const surfaceZoneGeom = needsHoleAnalysis && !skipHeavyHover
            ? getCylindricalZoneGeometry(mesh, faceIndex, worldNormal)
            : null
          const buildFastFaceTriangle = () => {
            const vA = new THREE.Vector3(
              pos.getX(face.a),
              pos.getY(face.a),
              pos.getZ(face.a),
            ).applyMatrix4(mesh.matrixWorld)
            const vB = new THREE.Vector3(
              pos.getX(face.b),
              pos.getY(face.b),
              pos.getZ(face.b),
            ).applyMatrix4(mesh.matrixWorld)
            const vC = new THREE.Vector3(
              pos.getX(face.c),
              pos.getY(face.c),
              pos.getZ(face.c),
            ).applyMatrix4(mesh.matrixWorld)
            const g = new THREE.BufferGeometry().setAttribute(
              'position',
              new THREE.Float32BufferAttribute(
                [vA.x, vA.y, vA.z, vB.x, vB.y, vB.z, vC.x, vC.y, vC.z],
                3,
              ),
            )
            g.computeVertexNormals()
            return g
          }
          const surfaceFaceGeom =
            surfaceZoneGeom ??
            (needsHoleAnalysis ? getCoplanarFaceGeometry(mesh, faceIndex) : null) ??
            buildFastFaceTriangle()
          const surfaceMat = new THREE.MeshBasicMaterial({
            color: 0x4488ff,
            transparent: true,
            opacity: 0.35,
            side: THREE.DoubleSide,
            depthWrite: false,
            depthTest: false,
          })
          highlightGroup.add(new THREE.Mesh(surfaceFaceGeom, surfaceMat))

          let candidates = getSnapCandidates(hit)
          const showHoleCylinderHighlight = needsHoleAnalysis
          if (holeInfo) {
            const n = holeInfo.normal
            const u = new THREE.Vector3().crossVectors(n, new THREE.Vector3(1, 0, 0)).normalize()
            if (u.lengthSq() < 0.01) u.crossVectors(n, new THREE.Vector3(0, 1, 0)).normalize()
            const v = new THREE.Vector3().crossVectors(n, u).normalize()
            const r = holeInfo.radius
            candidates = mergeSnapCandidates(candidates, [
              holeInfo.center.clone(),
              holeInfo.center.clone().add(u.clone().multiplyScalar(r)),
              holeInfo.center.clone().sub(u.clone().multiplyScalar(r)),
              holeInfo.center.clone().add(v.clone().multiplyScalar(r)),
              holeInfo.center.clone().sub(v.clone().multiplyScalar(r)),
            ], 'face')
            if (showHoleCylinderHighlight) {
              const rimPts: THREE.Vector3[] = []
              for (let i = 0; i <= 64; i++) {
                const t = (i / 64) * Math.PI * 2
                rimPts.push(
                  holeInfo.center
                    .clone()
                    .add(u.clone().multiplyScalar(r * Math.cos(t)))
                    .add(v.clone().multiplyScalar(r * Math.sin(t))),
                )
              }
              const rimGeom = new THREE.BufferGeometry().setFromPoints(rimPts)
              const rimLine = new THREE.LineLoop(
                rimGeom,
                new THREE.LineBasicMaterial({ color: 0x00ff88, linewidth: 2 }),
              )
              highlightGroup.add(rimLine)
            }
          } else if (radiusInfo) {
            candidates = mergeSnapCandidates(candidates, [radiusInfo.center.clone()], 'face')
            if (showHoleCylinderHighlight) {
              const n = worldNormal
              const u = new THREE.Vector3().crossVectors(n, new THREE.Vector3(1, 0, 0)).normalize()
              if (u.lengthSq() < 0.01) u.crossVectors(n, new THREE.Vector3(0, 1, 0)).normalize()
              const v = new THREE.Vector3().crossVectors(n, u).normalize()
              const circlePts: THREE.Vector3[] = []
              for (let i = 0; i <= 64; i++) {
                const t = (i / 64) * Math.PI * 2
                circlePts.push(
                  radiusInfo.center
                    .clone()
                    .add(u.clone().multiplyScalar(radiusInfo.radius * Math.cos(t)))
                    .add(v.clone().multiplyScalar(radiusInfo.radius * Math.sin(t))),
                )
              }
              const circleGeom = new THREE.BufferGeometry().setFromPoints(circlePts)
              const circleLine = new THREE.LineLoop(
                circleGeom,
                new THREE.LineBasicMaterial({ color: 0x00cc88 }),
              )
              highlightGroup.add(circleLine)
            }
          }

          if (needsHoleAnalysis && holeInfo && hoverTooltipEl) {
            const screen = hit.point.clone().project(camera)
            hoverTooltipEl.style.left = (screen.x * 0.5 + 0.5) * rect.width + 'px'
            hoverTooltipEl.style.top = (-screen.y * 0.5 + 0.5) * rect.height + 'px'
            hoverTooltipEl.textContent = `Отверстие · D = ${(2 * holeInfo.radius).toFixed(2)}`
            hoverTooltipEl.style.display = 'block'
          } else if (needsHoleAnalysis && radiusInfo && hoverTooltipEl) {
            const screen = hit.point.clone().project(camera)
            hoverTooltipEl.style.left = (screen.x * 0.5 + 0.5) * rect.width + 'px'
            hoverTooltipEl.style.top = (-screen.y * 0.5 + 0.5) * rect.height + 'px'
            hoverTooltipEl.textContent = `R = ${radiusInfo.radius.toFixed(2)}`
            hoverTooltipEl.style.display = 'block'
          } else if (hoverTooltipEl) {
            hoverTooltipEl.style.display = 'none'
          }

          if (measureModeRef.value && camera) {
            const snapPt = getClosestSnapPoint(candidates, camera, mouse)
            if (snapPt) {
              const r = Math.max(1.5, adaptiveMeasurementScale(snapPt) * 0.06)
              const snapGeom = new THREE.SphereGeometry(r, 12, 12)
              const snapMat = new THREE.MeshBasicMaterial({
                color: 0xffcc00,
                depthTest: false,
                transparent: true,
                opacity: 0.95,
              })
              const snapMarker = new THREE.Mesh(snapGeom, snapMat)
              snapMarker.position.copy(snapPt)
              snapMarker.renderOrder = 999
              highlightGroup.add(snapMarker)
            }
            if (
              measureTypeRef.value === 'distance'
              && measurementPoints.length === 1
            ) {
              const previewPt = (snapPt ?? hit.point).clone()
              const moved = !measurePreviewPoint
                || measurePreviewPoint.distanceToSquared(previewPt) > MEASURE_PREVIEW_MOVE_THRESH_MM2
              if (moved) {
                measurePreviewPoint = previewPt
                updateMeasurementGraphics()
              }
            }
          }
        } else if (hoverTooltipEl) {
          hoverTooltipEl.style.display = 'none'
        }
      } else {
        if (hoverTooltipEl) hoverTooltipEl.style.display = 'none'
        lastHoverNormal = null
        lastHoverPoint = null
      }
      hoverDirty = false
      lastHoverUpdateAt = now
      }
    if (isCameraInteracting) {
      if (measurementLabelEl) measurementLabelEl.style.display = 'none'
      if (measurementLabelEl0) measurementLabelEl0.style.display = 'none'
      if (measurementLabelEl1) measurementLabelEl1.style.display = 'none'
      if (measurementLabelEl2) measurementLabelEl2.style.display = 'none'
      if (measurementPerpLabelEl) measurementPerpLabelEl.style.display = 'none'
      if (measurementExtraLabelEl) measurementExtraLabelEl.style.display = 'none'
      if (diameterSecondLabelEl) diameterSecondLabelEl.style.display = 'none'
    } else if (
      measurementPoints.length === 1
      && measurePreviewPoint
      && measureTypeRef.value === 'distance'
      && measureModeRef.value
      && containerRef.value
      && measurementLabelEl
    ) {
      const rect = containerRef.value.getBoundingClientRect()
      const A = measurementPoints[0]
      const B = measurePreviewPoint
      const d = A.distanceTo(B)
      const labelWorld = linearDimLabelWorldForAnchorPoints(A, B)
      labelWorld.project(camera)
      measurementLabelEl.style.left = `${(labelWorld.x * 0.5 + 0.5) * rect.width}px`
      measurementLabelEl.style.top = `${(-labelWorld.y * 0.5 + 0.5) * rect.height}px`
      measurementLabelEl.textContent = `${d.toFixed(2)} мм`
      measurementLabelEl.style.display = 'block'
      measurementLabelEl.style.fontSize = '14px'
      measurementLabelEl.style.fontWeight = '600'
      measurementLabelEl.style.border = '1px solid rgba(127,194,255,0.8)'
      if (measurementLabelEl0) measurementLabelEl0.style.display = 'none'
      if (measurementLabelEl1) measurementLabelEl1.style.display = 'none'
      if (measurementLabelEl2) measurementLabelEl2.style.display = 'none'
      if (measurementPerpLabelEl) measurementPerpLabelEl.style.display = 'none'
      if (measurementExtraLabelEl) measurementExtraLabelEl.style.display = 'none'
      if (diameterSecondLabelEl) diameterSecondLabelEl.style.display = 'none'
    } else if (measurementPoints.length === 2 && measureTypeRef.value === 'hole-center-distance' && containerRef.value && measurementLabelEl) {
      const rect = containerRef.value.getBoundingClientRect()
      const A = measurementPoints[0]
      const B = measurementPoints[1]
      const mid = A.clone().add(B).multiplyScalar(0.5)
      mid.project(camera)
      const d = A.distanceTo(B)
      measurementLabelEl.style.left = (mid.x * 0.5 + 0.5) * rect.width + 'px'
      measurementLabelEl.style.top = (-mid.y * 0.5 + 0.5) * rect.height + 'px'
      measurementLabelEl.textContent = d.toFixed(2)
      measurementLabelEl.style.display = 'block'
      if (measurementLabelEl0) measurementLabelEl0.style.display = 'none'
      if (measurementLabelEl1) measurementLabelEl1.style.display = 'none'
      if (measurementLabelEl2) measurementLabelEl2.style.display = 'none'
      if (measurementPerpLabelEl) measurementPerpLabelEl.style.display = 'none'
      if (measurementExtraLabelEl) measurementExtraLabelEl.style.display = 'none'
    } else if (measureTypeRef.value === 'diameter' && firstClickHole && secondHoleResult && measurementPoints.length === 2 && containerRef.value && measurementExtraLabelEl && diameterSecondLabelEl && measurementLabelEl && measurementLabelEl0 && measurementLabelEl1 && measurementLabelEl2) {
      const rect = containerRef.value.getBoundingClientRect()
      const A = measurementPoints[0]
      const B = measurementPoints[1]
      const delta = B.clone().sub(A)
      const perpComp = MEASURE_PLANE_NORMAL.clone().multiplyScalar(delta.dot(MEASURE_PLANE_NORMAL))
      const Bprime = B.clone().sub(perpComp)
      const L = A.distanceTo(B)
      const L_parallel = A.distanceTo(Bprime)
      const L_perp = Bprime.distanceTo(B)
      const midpoints = [
        A.clone().add(B).multiplyScalar(0.5),
        A.clone().add(Bprime).multiplyScalar(0.5),
        Bprime.clone().add(B).multiplyScalar(0.5),
      ]
      const texts = [`${L.toFixed(2)}`, `${L_parallel.toFixed(2)}`, `${L_perp.toFixed(2)}`]
      const labels = [measurementLabelEl0, measurementLabelEl1, measurementLabelEl2]
      for (let i = 0; i < 3; i++) {
        midpoints[i].project(camera)
        labels[i].style.left = (midpoints[i].x * 0.5 + 0.5) * rect.width + 'px'
        labels[i].style.top = (-midpoints[i].y * 0.5 + 0.5) * rect.height + 'px'
        labels[i].textContent = texts[i]
        labels[i].style.display = 'block'
      }
      const p1 = firstClickHole.center.clone()
      p1.project(camera)
      measurementExtraLabelEl.style.left = (p1.x * 0.5 + 0.5) * rect.width + 'px'
      measurementExtraLabelEl.style.top = (-p1.y * 0.5 + 0.5) * rect.height + 'px'
      measurementExtraLabelEl.textContent = (2 * firstClickHole.radius).toFixed(2)
      measurementExtraLabelEl.style.display = 'block'
      const p2 = secondHoleResult.center.clone()
      p2.project(camera)
      diameterSecondLabelEl.style.left = (p2.x * 0.5 + 0.5) * rect.width + 'px'
      diameterSecondLabelEl.style.top = (-p2.y * 0.5 + 0.5) * rect.height + 'px'
      diameterSecondLabelEl.textContent = (2 * secondHoleResult.radius).toFixed(2)
      diameterSecondLabelEl.style.display = 'block'
      const mid = A.clone().add(B).multiplyScalar(0.5)
      mid.project(camera)
      measurementLabelEl.style.left = (mid.x * 0.5 + 0.5) * rect.width + 'px'
      measurementLabelEl.style.top = (-mid.y * 0.5 + 0.5) * rect.height + 'px'
      measurementLabelEl.textContent = L.toFixed(2)
      measurementLabelEl.style.display = 'block'
      if (measurementPerpLabelEl) measurementPerpLabelEl.style.display = 'none'
    } else if (radiusOrDiameterResult && measurementExtraLabelEl && containerRef.value) {
      const rect = containerRef.value.getBoundingClientRect()
      const proj = radiusOrDiameterResult.center.clone()
      proj.project(camera)
      const cx = proj.x
      const cy = proj.y
      measurementExtraLabelEl.style.left = (cx * 0.5 + 0.5) * rect.width + 'px'
      measurementExtraLabelEl.style.top = (-cy * 0.5 + 0.5) * rect.height + 'px'
      const r = radiusOrDiameterResult.radius
      measurementExtraLabelEl.textContent = radiusOrDiameterResult.isDiameter ? `${(2 * r).toFixed(2)}` : `${r.toFixed(2)}`
      measurementExtraLabelEl.style.display = 'block'
      if (measurementLabelEl) measurementLabelEl.style.display = 'none'
      if (measurementLabelEl0) measurementLabelEl0.style.display = 'none'
      if (measurementLabelEl1) measurementLabelEl1.style.display = 'none'
      if (measurementLabelEl2) measurementLabelEl2.style.display = 'none'
      if (measurementPerpLabelEl) measurementPerpLabelEl.style.display = 'none'
      if (diameterSecondLabelEl) diameterSecondLabelEl.style.display = 'none'
    } else if (arcResult && measurementExtraLabelEl && containerRef.value) {
      const rect = containerRef.value.getBoundingClientRect()
      const path = arcResult.path
      const mid = path.length > 0 ? path[Math.floor(path.length / 2)].clone() : new THREE.Vector3(0, 0, 0)
      mid.project(camera)
      measurementExtraLabelEl.style.left = (mid.x * 0.5 + 0.5) * rect.width + 'px'
      measurementExtraLabelEl.style.top = (-mid.y * 0.5 + 0.5) * rect.height + 'px'
      measurementExtraLabelEl.textContent = arcResult.length.toFixed(2)
      measurementExtraLabelEl.style.display = 'block'
      if (measurementLabelEl) measurementLabelEl.style.display = 'none'
      if (measurementLabelEl0) measurementLabelEl0.style.display = 'none'
      if (measurementLabelEl1) measurementLabelEl1.style.display = 'none'
      if (measurementLabelEl2) measurementLabelEl2.style.display = 'none'
      if (measurementPerpLabelEl) measurementPerpLabelEl.style.display = 'none'
    } else {
      if (measurementLabelEl) measurementLabelEl.style.display = 'none'
      if (measurementLabelEl0) measurementLabelEl0.style.display = 'none'
      if (measurementLabelEl1) measurementLabelEl1.style.display = 'none'
      if (measurementLabelEl2) measurementLabelEl2.style.display = 'none'
      if (measurementPerpLabelEl) measurementPerpLabelEl.style.display = 'none'
      if (measurementExtraLabelEl) measurementExtraLabelEl.style.display = 'none'
    }
    if (!isCameraInteracting) {
      updateSavedMeasurementLabelPositions()
    } else {
      for (const el of savedMeasurementLabelById.values()) el.style.display = 'none'
    }
    }
    renderer.render(scene, camera)
  }
  animate()

  window.addEventListener('resize', onResize)
}

function onResize() {
  if (!containerRef.value || !camera || !renderer) return
  const w = containerRef.value.clientWidth
  const h = containerRef.value.clientHeight
  camera.aspect = w / h
  camera.updateProjectionMatrix()
  idlePixelRatio = Math.min(window.devicePixelRatio, 2)
  renderer.setPixelRatio(isCameraInteracting ? Math.min(INTERACTION_PIXEL_RATIO, idlePixelRatio) : idlePixelRatio)
  renderer.setSize(w, h)
  controls?.handleResize()
}

function centerModel(box: THREE.Box3) {
  applyAutoNavigationLimits()
  updateSceneLighting(box)
  const center = box.getCenter(new THREE.Vector3())
  const size = box.getSize(new THREE.Vector3())
  const maxDim = Math.max(size.x, size.y, size.z, 1e-9)
  loadedSceneCharDim = maxDim
  const minDim = Math.min(size.x, size.y, size.z)
  /** Почти плоский bbox (тонкий лист в одной плоскости). */
  const isFlatSheet = maxDim > 1e-6 && minDim / maxDim < 0.03
  let thinAxis = 1
  if (isFlatSheet) {
    if (size.x <= size.y && size.x <= size.z) thinAxis = 0
    else if (size.y <= size.x && size.y <= size.z) thinAxis = 1
    else thinAxis = 2
  }
  const planeSpan = isFlatSheet
    ? thinAxis === 0
      ? Math.max(size.y, size.z)
      : thinAxis === 1
        ? Math.max(size.x, size.z)
        : Math.max(size.x, size.y)
    : maxDim
  const distance = planeSpan * 1.45
  if (camera instanceof THREE.PerspectiveCamera && maxDim > 0) {
    camera.far = Math.max(500_000, maxDim * 25)
    camera.updateProjectionMatrix()
  }
  if (isFlatSheet) {
    if (thinAxis === 0) camera.position.set(center.x + distance, center.y, center.z)
    else if (thinAxis === 1) camera.position.set(center.x, center.y + distance, center.z)
    else camera.position.set(center.x, center.y, center.z + distance)
  } else {
    camera.position.set(center.x + distance * 0.6, center.y + distance * 0.5, center.z + distance * 0.6)
  }
  controls.target.copy(center)
  controls.update()
  savedCameraPosition.copy(camera.position)
  savedCameraTarget.copy(controls.target)
  if (axesHelper && maxDim > 0) {
    const axesLen = Math.max((isFlatSheet ? planeSpan : maxDim) * 0.15, 10)
    axesHelper.scale.setScalar(axesLen / 100)
  }
  updateGroundGrid(box)
  updateCameraClipPlanes()
}

function resetView() {
  if (!camera || !controls) return
  camera.position.copy(savedCameraPosition)
  controls.target.copy(savedCameraTarget)
  controls.update()
}

/** Delete / Backspace: разметка замечания → измерение → замечание → модель (на вкладке «Модели»). */
function handleViewerDeleteKey(): boolean {
  if (
    isRemarksPanelActive.value &&
    remarkScreenLayerEditable.value &&
    (remarkScreenSelectedShapeId.value || remarkScreenSelectedImageId.value)
  ) {
    deleteSelectedScreenMarkup()
    return true
  }
  if (selectedMeasurementId.value) {
    const id = selectedMeasurementId.value
    if (measurementHistory.value.some((m) => m.id === id)) {
      removeMeasurement(id)
      return true
    }
  }
  if (selectedRemarkId.value) {
    deleteRemarkById(selectedRemarkId.value, true)
    return true
  }
  if (leftSidebarTab.value === 'tree' && focusedModelId.value && modelGroupsById.has(focusedModelId.value)) {
    deleteFocusedModel()
    return true
  }
  return false
}

function focusModelInView() {
  if (!camera || !controls || !meshGroup || meshGroup.children.length === 0) return
  const box = getReferenceSceneBox() ?? new THREE.Box3().setFromObject(meshGroup)
  if (box.isEmpty()) return
  const center = box.getCenter(new THREE.Vector3())
  const size = box.getSize(new THREE.Vector3())
  const maxDim = Math.max(size.x, size.y, size.z, 1)
  const direction = camera.position.clone().sub(controls.target)
  if (direction.lengthSq() < 1e-8) direction.set(1, 0.75, 1)
  direction.normalize()
  camera.position.copy(center).add(direction.multiplyScalar(maxDim * 1.45))
  controls.target.copy(center)
  controls.update()
}

function onWindowKeyDown(ev: KeyboardEvent) {
  const target = ev.target as HTMLElement | null
  if (target) {
    const tag = target.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable) return
  }
  const mod = ev.ctrlKey || ev.metaKey
  if (mod && ev.code === 'KeyZ') {
    ev.preventDefault()
    if (ev.shiftKey) redoTransform()
    else undoTransform()
    return
  }
  if (mod && ev.code === 'KeyY') {
    ev.preventDefault()
    redoTransform()
    return
  }
  if (mod && ev.code === 'KeyC') {
    ev.preventDefault()
    copyFocusedTransform()
    return
  }
  if (mod && ev.code === 'KeyV') {
    ev.preventDefault()
    pasteTransformToFocused()
    return
  }
  if (ev.code === 'Delete' || ev.code === 'Backspace') {
    if (handleViewerDeleteKey()) {
      ev.preventDefault()
    }
    return
  }
  if (ev.code === 'Escape') {
    ev.preventDefault()
    if (boxSelectDrag || boxSelectRect.value) {
      detachBoxSelectWindowListeners()
      boxSelectDrag = null
      boxSelectRect.value = null
      if (controls) controls.enabled = true
      return
    }
    if (placementActive.value) {
      cancelModelPlacement()
      return
    }
    const cadInProgress = !!(cadLinearPlane1.value || cadLinearPlane2.value || cadLinearPickTarget.value)
    const measureInProgress = measurementPoints.length > 0 || measurePreviewPoint || cadInProgress
    if (measureModeRef.value && measureInProgress) {
      clearMeasurements()
      clearCadLinearPicks()
      cadLinearPickTarget.value = null
      if (measureTypeRef.value === 'cad-linear') {
        beginNextCadLinearDimension()
      } else if (measureTypeRef.value === 'distance') {
        measureStatusHint.value = 'Кликните 1-ю точку на модели.'
      }
      return
    }
    if (
      selectedPartRowKeys.value.size > 0
      || selectedComponentRowId.value
      || partTreeIsolateState.value
      || partFocusActive.value
    ) {
      resetPartSelectionAndView()
      focusedModelId.value = null
      return
    }
    modelRotateMode.value = false
    clearPendingAssemblyPlaneSelections()
    clearMeasurements()
    setMeasureMode(false)
    if (props.measureMode) {
      emit('measure')
    }
    if (props.sectionMode) {
      emit('section-mode')
    }
    selectedFacePoint = null
    selectedFaceNormal = null
    return
  }
  if (ev.code === 'KeyF') {
    ev.preventDefault()
    focusModelInView()
  }
}

type ViewPreset = 'front' | 'back' | 'top' | 'bottom' | 'left' | 'right' | 'iso' | 'dimetric'

const orientationDropdownOpen = ref(false)
const orientationDropdownRef = ref<HTMLDivElement | null>(null)
const mouseSettingsDropdownOpen = ref(false)
const mouseSettingsDropdownRef = ref<HTMLDivElement | null>(null)
const mousePreset = ref<'cad' | 'smooth' | 'fast'>('cad')

function applyMousePreset(preset: 'cad' | 'smooth' | 'fast') {
  mousePreset.value = preset
  if (preset === 'cad') {
    mouseZoomSpeed.value = 0.028
    mouseRotateSpeed.value = 5.8
    mousePanSpeed.value = 1.8
    mouseDamping.value = 0.2
    mouseZoomGestureMs.value = 420
  } else if (preset === 'smooth') {
    mouseZoomSpeed.value = 0.022
    mouseRotateSpeed.value = 4.8
    mousePanSpeed.value = 1.5
    mouseDamping.value = 0.3
    mouseZoomGestureMs.value = 520
  } else {
    mouseZoomSpeed.value = 0.04
    mouseRotateSpeed.value = 7.2
    mousePanSpeed.value = 2.4
    mouseDamping.value = 0.16
    mouseZoomGestureMs.value = 320
  }
  applyMouseSettings()
}

function onOrientationClickOutside(ev: MouseEvent) {
  if (!orientationDropdownOpen.value) return
  const el = orientationDropdownRef.value
  if (el && !el.contains(ev.target as Node)) orientationDropdownOpen.value = false
}

function onMouseSettingsClickOutside(ev: MouseEvent) {
  if (!mouseSettingsDropdownOpen.value) return
  const el = mouseSettingsDropdownRef.value
  if (el && !el.contains(ev.target as Node)) mouseSettingsDropdownOpen.value = false
}

const ORIENTATION_OPTIONS: { id: ViewPreset; label: string; tooltip: string; hasIcon: boolean }[] = [
  { id: 'front', label: 'П', tooltip: 'Вид спереди', hasIcon: true },
  { id: 'back', label: 'З', tooltip: 'Вид сзади', hasIcon: true },
  { id: 'top', label: 'В', tooltip: 'Вид сверху', hasIcon: true },
  { id: 'bottom', label: 'Н', tooltip: 'Вид снизу', hasIcon: true },
  { id: 'left', label: 'Л', tooltip: 'Вид слева', hasIcon: true },
  { id: 'right', label: 'Пр', tooltip: 'Вид справа', hasIcon: true },
  { id: 'iso', label: 'Изометрия', tooltip: 'Изометрия', hasIcon: false },
  { id: 'dimetric', label: 'Диметрия', tooltip: 'Диметрия', hasIcon: false },
]

function setViewOrientation(preset: ViewPreset) {
  if (!camera || !controls || !meshGroup || meshGroup.children.length === 0) return
  orientationDropdownOpen.value = false
  const box = new THREE.Box3().setFromObject(meshGroup)
  const center = box.getCenter(new THREE.Vector3())
  const size = box.getSize(new THREE.Vector3())
  const maxDim = Math.max(size.x, size.y, size.z, 1)
  const distance = maxDim * 1.5
  const dir = new THREE.Vector3()
  switch (preset) {
    case 'front':
      dir.set(0, 0, 1)
      break
    case 'back':
      dir.set(0, 0, -1)
      break
    case 'top':
      dir.set(0, 1, 0)
      break
    case 'bottom':
      dir.set(0, -1, 0)
      break
    case 'left':
      dir.set(-1, 0, 0)
      break
    case 'right':
      dir.set(1, 0, 0)
      break
    case 'iso':
      dir.set(1, 1, 1).normalize()
      break
    case 'dimetric':
      dir.set(2, 1, 2).normalize()
      break
    default:
      return
  }
  camera.position.copy(center).add(dir.multiplyScalar(distance))
  controls.target.copy(center)
  controls.update()
}

function viewPerpendicularToFace() {
  if (!camera || !controls || !meshGroup?.children.length) return
  if (!selectedFacePoint || !selectedFaceNormal) {
    logger.warn('Viewer3D', 'Сначала кликните по грани модели')
    return
  }
  const box = new THREE.Box3().setFromObject(meshGroup)
  const size = box.getSize(new THREE.Vector3())
  const maxDim = Math.max(size.x, size.y, size.z, 1)
  const distance = maxDim * 1.5
  const n = selectedFaceNormal.clone().normalize()
  controls.target.copy(selectedFacePoint)
  camera.position.copy(selectedFacePoint).add(n.clone().multiplyScalar(distance))
  // Ориентация: грань параллельна экрану, мировой «верх» — вертикально на экране
  const worldUp = new THREE.Vector3(0, 1, 0)
  const upOnPlane = worldUp.clone().sub(n.clone().multiplyScalar(worldUp.dot(n)))
  if (upOnPlane.lengthSq() < 1e-6) {
    upOnPlane.set(0, 0, 1)
    if (Math.abs(n.dot(upOnPlane)) > 0.99) upOnPlane.set(1, 0, 0)
  }
  upOnPlane.normalize()
  camera.up.copy(upOnPlane)
  camera.lookAt(selectedFacePoint)
  controls.update()
}

function disposeWireframeEdgeChild(ch: THREE.Object3D) {
  if (!(ch instanceof THREE.LineSegments)) return
  ch.geometry?.dispose()
  const mat = ch.material
  if (Array.isArray(mat)) mat.forEach((m) => m.dispose())
  else mat?.dispose()
}

function removeWireframeEdgesFromObject(root: THREE.Object3D) {
  root.traverse((o: THREE.Object3D) => {
    if (!(o instanceof THREE.Mesh)) return
    delete o.userData.wireframeEdgeAttached
    for (let i = o.children.length - 1; i >= 0; i--) {
      const ch = o.children[i]
      if (!ch.userData?.wireframeEdge) continue
      o.remove(ch)
      disposeWireframeEdgeChild(ch)
    }
  })
}

function attachWireframeEdgesToMesh(mesh: THREE.Mesh) {
  if (mesh.userData.wireframeEdgeAttached || !mesh.geometry) return
  const pos = mesh.geometry.attributes.position
  if (!pos || pos.count < 3) return
  const edges = new THREE.EdgesGeometry(mesh.geometry, WIREFRAME_EDGE_THRESHOLD_DEG)
  const lineOpacity = frameOpacityRef.value
  const mat = new THREE.LineBasicMaterial({
    color: 0x141820,
    transparent: lineOpacity < 0.999,
    opacity: lineOpacity,
    depthTest: true,
  })
  const lines = new THREE.LineSegments(edges, mat)
  lines.userData.wireframeEdge = true
  lines.raycast = noopRaycast
  lines.renderOrder = 2
  mesh.add(lines)
  mesh.userData.wireframeEdgeAttached = true
}

function updateWireframeEdgeLineOpacity() {
  if (!meshGroup) return
  const lineOpacity = frameOpacityRef.value
  meshGroup.traverse((o: THREE.Object3D) => {
    if (!(o instanceof THREE.Mesh)) return
    o.children.forEach((ch) => {
      if (!ch.userData?.wireframeEdge || !(ch instanceof THREE.LineSegments)) return
      const m = ch.material as THREE.LineBasicMaterial
      m.opacity = lineOpacity
      m.transparent = lineOpacity < 0.999
      m.needsUpdate = true
    })
  })
}

/** Глобальный каркас (кнопка «Каркас») — линии по контуру, грани скрыты. */
function syncWireframeEdges(scope?: THREE.Object3D) {
  if (!meshGroup) return
  if (!wireframeModeRef.value) {
    removeWireframeEdgesFromObject(meshGroup)
    restoreWireframeFaceGhost()
    return
  }
  removeWireframeEdgesFromObject(scope ?? meshGroup)
  let built = 0
  meshGroup.traverse((o: THREE.Object3D) => {
    if (built >= WIREFRAME_MAX_EDGE_MESHES) return
    if (!(o instanceof THREE.Mesh) || !o.visible) return
    attachWireframeEdgesToMesh(o)
    built += 1
  })
  syncWireframeFaceGhost()
}

function setMeshWireframeFaceGhost(mesh: THREE.Mesh, ghost: boolean) {
  if (!mesh.material) return
  const arr = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
  if (ghost) {
    if (!wireframeFaceMatBackup.has(mesh)) {
      wireframeFaceMatBackup.set(
        mesh,
        arr.map((m) => {
          const mm = m as THREE.Material & { opacity?: number; transparent?: boolean; depthWrite?: boolean }
          return {
            transparent: !!mm.transparent,
            opacity: typeof mm.opacity === 'number' ? mm.opacity : 1,
            depthWrite: mm.depthWrite !== false,
          }
        }),
      )
    }
    arr.forEach((m) => {
      const mm = m as THREE.Material & { opacity?: number; transparent?: boolean; depthWrite?: boolean }
      mm.transparent = true
      mm.opacity = WIREFRAME_GHOST_FACE_OPACITY
      mm.depthWrite = false
      mm.needsUpdate = true
    })
    return
  }
  const backup = wireframeFaceMatBackup.get(mesh)
  if (backup) {
    arr.forEach((m, i) => {
      const mm = m as THREE.Material & { opacity?: number; transparent?: boolean; depthWrite?: boolean }
      const b = backup[i]
      if (!b) return
      mm.transparent = b.transparent
      mm.opacity = b.opacity
      mm.depthWrite = b.depthWrite
      mm.needsUpdate = true
    })
    wireframeFaceMatBackup.delete(mesh)
  }
  applyUserOpacityToMesh(mesh)
}

function restoreWireframeFaceGhost() {
  ;[...wireframeFaceMatBackup.keys()].forEach((mesh) => setMeshWireframeFaceGhost(mesh, false))
  wireframeFaceMatBackup.clear()
}

function syncWireframeFaceGhost() {
  if (!meshGroup) return
  if (!wireframeModeRef.value) {
    restoreWireframeFaceGhost()
    return
  }
  meshGroup.traverse((o: THREE.Object3D) => {
    if (!(o instanceof THREE.Mesh)) return
    if (o.visible) setMeshWireframeFaceGhost(o, true)
    else if (wireframeFaceMatBackup.has(o)) setMeshWireframeFaceGhost(o, false)
  })
}

function resetMeshMaterialOpacity(mesh: THREE.Mesh) {
  if (!mesh.material) return
  const arr = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
  arr.forEach((m) => {
    const mm = m as THREE.Material & { opacity?: number; transparent?: boolean; depthWrite?: boolean }
    mm.transparent = false
    mm.opacity = 1
    mm.depthWrite = true
    mm.needsUpdate = true
  })
}

function applyUserOpacityToMesh(mesh: THREE.Mesh) {
  if (wireframeFaceMatBackup.has(mesh)) return
  if (!mesh.material) return
  const op = meshUserOpacityByUuid.value[mesh.uuid] ?? 1
  const arr = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
  arr.forEach((m: THREE.Material) => {
    const mat = m as THREE.Material & { transparent?: boolean; opacity?: number; depthWrite?: boolean }
    const transparent = op < 0.999
    if ('transparent' in mat) mat.transparent = transparent
    if ('opacity' in mat) mat.opacity = op
    if ('depthWrite' in mat) mat.depthWrite = !transparent || op > 0.92
    mat.needsUpdate = true
  })
}

function applyUserOpacityToMeshGroup(scope?: THREE.Object3D) {
  const root = scope ?? meshGroup
  if (!root) return
  root.traverse((o: THREE.Object3D) => {
    if (o instanceof THREE.Mesh) applyUserOpacityToMesh(o)
  })
}

function setMeshesUserOpacity(uuids: string[], opacity: number) {
  const next = { ...meshUserOpacityByUuid.value }
  for (const uuid of uuids) {
    if (opacity >= 0.999) delete next[uuid]
    else next[uuid] = Math.max(0.05, Math.min(1, opacity))
  }
  meshUserOpacityByUuid.value = next
  for (const uuid of uuids) {
    const mesh = findMeshByUuid(uuid)
    if (!mesh) continue
    if (wireframeFaceMatBackup.has(mesh)) continue
    if (opacity >= 0.999) resetMeshMaterialOpacity(mesh)
    applyUserOpacityToMesh(mesh)
  }
}

function collectAllMeshUuidsInModel(modelId: string): string[] {
  const g = modelGroupsById.get(modelId)
  const uuids: string[] = []
  g?.traverse((o) => {
    if (o instanceof THREE.Mesh) uuids.push(o.uuid)
  })
  return uuids
}

function clearMeshesUserOpacity(uuids: string[]) {
  if (uuids.length === 0) return
  const next = { ...meshUserOpacityByUuid.value }
  for (const uuid of uuids) delete next[uuid]
  meshUserOpacityByUuid.value = next
  for (const uuid of uuids) {
    const mesh = findMeshByUuid(uuid)
    if (!mesh) continue
    if (!wireframeFaceMatBackup.has(mesh)) resetMeshMaterialOpacity(mesh)
    applyUserOpacityToMesh(mesh)
  }
}

function collectMeshesUnderPart(part: THREE.Object3D): THREE.Mesh[] {
  const list: THREE.Mesh[] = []
  part.traverse((o) => {
    if (o instanceof THREE.Mesh) list.push(o)
  })
  return list
}

function findTreeRowIdForMesh(modelId: string, part: THREE.Object3D): string | null {
  const rows = componentTreeRowsByModel.value[modelId]
  if (!rows) return null
  const uuids = new Set(collectMeshesUnderPart(part).map((m) => m.uuid))
  for (const r of rows) {
    if (r.targetIds?.some((id) => uuids.has(id))) return r.id
  }
  return null
}

function getContextMenuTargetMeshUuids(scope: 'mesh' | 'row'): string[] {
  const mid = contextMenuTargetModelId.value
  const part = contextMenuTargetPart
  if (!mid || !part) return []
  if (scope === 'row') {
    const rowId = findTreeRowIdForMesh(mid, part)
    if (rowId) return collectTargetIdsForTreeNode(mid, rowId)
  }
  return collectMeshesUnderPart(part).map((m) => m.uuid)
}

function setContextMenuOpacity(opacity: number, scope: 'mesh' | 'row' | 'model') {
  const mid = contextMenuTargetModelId.value
  if (!mid) return
  let uuids: string[] = []
  if (scope === 'model') uuids = collectAllMeshUuidsInModel(mid)
  else uuids = getContextMenuTargetMeshUuids(scope === 'row' ? 'row' : 'mesh')
  if (uuids.length === 0) return
  setMeshesUserOpacity(uuids, opacity)
  partContextMenuOpen.value = false
  contextMenuTargetPart = null
  contextMenuTargetModelId.value = null
}

function resetContextMenuOpacity(scope: 'mesh' | 'model') {
  const mid = contextMenuTargetModelId.value
  if (!mid) return
  const uuids =
    scope === 'model' ? collectAllMeshUuidsInModel(mid) : getContextMenuTargetMeshUuids('mesh')
  clearMeshesUserOpacity(uuids)
  partContextMenuOpen.value = false
  contextMenuTargetPart = null
  contextMenuTargetModelId.value = null
}

function toggleWireframe() {
  wireframeModeRef.value = !wireframeModeRef.value
  syncWireframeEdges()
  if (renderer && containerRef.value) {
    const pr = wireframeModeRef.value ? 1 : Math.min(window.devicePixelRatio, 2)
    renderer.setPixelRatio(pr)
    renderer.setSize(containerRef.value.clientWidth, containerRef.value.clientHeight)
  }
}

function applySectionToMeshGroup(plane: THREE.Plane | null) {
  const planes = plane ? [plane] : []
  const applyToGroup = (group: THREE.Group) => group.traverse((obj: THREE.Object3D) => {
    if (obj instanceof THREE.Mesh && obj.material) {
      const mat = obj.material
      const arr = Array.isArray(mat) ? mat : [mat]
      arr.forEach((m: THREE.Material) => {
        if ('clippingPlanes' in m) {
          (m as THREE.Material & { clippingPlanes: THREE.Plane[] }).clippingPlanes = planes
        }
      })
    }
  })
  applyToGroup(meshGroup)
  if (overlayGroup) applyToGroup(overlayGroup)
}

function applySectionPlane() {
  if (!sectionPlane || !currentSectionAxis) return
  const point =
    currentSectionAxis === 'x'
      ? new THREE.Vector3(currentSectionOffset, 0, 0)
      : currentSectionAxis === 'y'
        ? new THREE.Vector3(0, currentSectionOffset, 0)
        : new THREE.Vector3(0, 0, currentSectionOffset)
  const normal =
    currentSectionAxis === 'x'
      ? new THREE.Vector3(1, 0, 0)
      : currentSectionAxis === 'y'
        ? new THREE.Vector3(0, 1, 0)
        : new THREE.Vector3(0, 0, 1)
  sectionPlane.setFromNormalAndCoplanarPoint(normal, point)
  applySectionToMeshGroup(sectionPlane)
}

function setSectionAxis(axis: 'x' | 'y' | 'z' | null, offset?: number) {
  currentSectionAxis = axis
  if (typeof offset === 'number') currentSectionOffset = offset
  if (!sectionPlane) sectionPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)
  if (axis === null) {
    applySectionToMeshGroup(null)
    return
  }
  applySectionPlane()
}

function setSectionOffset(offset: number) {
  const o = Math.max(SECTION_OFFSET_MIN, Math.min(SECTION_OFFSET_MAX, offset))
  if (sectionPlaneMesh?.visible && sectionPlaneBasePoint && sectionPlaneNormal && sectionPlaneClipNormal) {
    sectionPlaneOffset = o
    const pt = sectionPlaneBasePoint.clone().add(sectionPlaneNormal.clone().multiplyScalar(o))
    if (sectionPlane) {
      sectionPlane.setFromNormalAndCoplanarPoint(sectionPlaneClipNormal, pt)
      applySectionToMeshGroup(sectionPlane)
    }
    sectionPlaneMesh.position.copy(pt)
  } else {
    currentSectionOffset = o
    if (currentSectionAxis) applySectionPlane()
  }
}

function getSectionOffset(): number {
  if (sectionPlaneMesh?.visible) return sectionPlaneOffset
  if (currentSectionAxis != null) return currentSectionOffset
  return 0
}

function isSectionActive(): boolean {
  return !!(sectionPlaneMesh?.visible) || currentSectionAxis != null
}

function setSectionFromHit(point: THREE.Vector3, worldNormal: THREE.Vector3) {
  worldNormal.normalize()
  sectionPlaneBasePoint = point.clone()
  sectionPlaneNormal = worldNormal.clone()
  sectionPlaneClipNormal = worldNormal.clone().negate()
  sectionPlaneOffset = 0
  if (!sectionPlane) sectionPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)
  sectionPlane.setFromNormalAndCoplanarPoint(sectionPlaneClipNormal, point)
  applySectionToMeshGroup(sectionPlane)
  if (!sectionPlaneMesh) {
    const geom = new THREE.PlaneGeometry(5000, 5000)
    const mat = new THREE.MeshBasicMaterial({
      color: 0x4488ff,
      transparent: true,
      opacity: 0.28,
      side: THREE.DoubleSide,
      depthWrite: false,
    })
    sectionPlaneMesh = new THREE.Mesh(geom, mat)
    scene.add(sectionPlaneMesh)
  }
  sectionPlaneMesh.position.copy(point)
  sectionPlaneMesh.quaternion.setFromUnitVectors(
    new THREE.Vector3(0, 0, 1),
    worldNormal.clone().normalize()
  )
  sectionPlaneMesh.visible = true
  emit('section-active')
  emit('section-offset-changed', 0)
}

function clearSection() {
  applySectionToMeshGroup(null)
  if (sectionPlaneMesh) {
    sectionPlaneMesh.visible = false
  }
  sectionPlaneBasePoint = null
  sectionPlaneNormal = null
  sectionPlaneClipNormal = null
  emit('section-inactive')
}

function setSectionMode(enabled: boolean) {
  sectionModeRef.value = enabled
  logger.info('Viewer3D', `Режим сечения: ${enabled ? 'вкл' : 'выкл'}`)
}

function clampOffset(v: number) {
  return Math.min(SECTION_OFFSET_MAX, Math.max(SECTION_OFFSET_MIN, v))
}

function onHeaderOffsetInput(ev: Event) {
  const val = parseFloat((ev.target as HTMLInputElement).value)
  if (Number.isFinite(val)) emit('update:sectionOffset', clampOffset(val))
}

function onHeaderOffsetWheel(ev: WheelEvent, current: number) {
  ev.preventDefault()
  const delta = ev.deltaY > 0 ? -SECTION_OFFSET_STEP : SECTION_OFFSET_STEP
  emit('update:sectionOffset', clampOffset(current + delta))
}

function updateMouseFromClient(clientX: number, clientY: number) {
  if (!renderer?.domElement) return
  const rect = renderer.domElement.getBoundingClientRect()
  mouse.x = ((clientX - rect.left) / rect.width) * 2 - 1
  mouse.y = -((clientY - rect.top) / rect.height) * 2 + 1
}

/** Точка на детали под курсором — центр вращения сцены (ПКМ). */
function pickOrbitPivotFromClient(clientX: number, clientY: number): THREE.Vector3 | null {
  if (!camera || !renderer || !meshGroup?.children.length) return null
  updateMouseFromClient(clientX, clientY)
  raycaster.setFromCamera(mouse, camera)
  meshGroup.updateMatrixWorld(true)
  const hit = pickSolidSurfaceHit(intersectPickableMeshes(raycaster))
  return hit ? hit.point.clone() : null
}

/** Точка на трекболе (как в TrackballControls._getMouseOnCircle). */
function syncTrackballMouseOnCircle(pageX: number, pageY: number) {
  if (!controls?.domElement) return
  controls.handleResize()
  const s = controls.screen
  const x = (pageX - s.width * 0.5 - s.left) / (s.width * 0.5)
  const y = (s.height + 2 * (s.top - pageY)) / s.width
  controls._moveCurr.set(x, y)
  controls._movePrev.copy(controls._moveCurr)
}

/** Синхронизация TrackballControls после смены target. */
function syncTrackballAfterPivotChange() {
  if (!camera || !controls) return
  controls._eye.subVectors(camera.position, controls.target)
  controls._lastPosition.copy(camera.position)
  controls._lastAngle = 0
  savedCameraTarget.copy(controls.target)
}

/**
 * Новый центр вращения на детали: camera и target сдвигаются на один вектор —
 * на экране картинка не меняется (параллельный перенос).
 */
function applyOrbitPivotInvisibly(worldPoint: THREE.Vector3) {
  if (!camera || !controls) return
  if (controls.target.distanceTo(worldPoint) < ORBIT_PIVOT_MIN_SHIFT_MM) return
  const delta = worldPoint.clone().sub(controls.target)
  controls.target.add(delta)
  camera.position.add(delta)
  syncTrackballAfterPivotChange()
}

/** Pivot — только после порога перетаскивания (клик под меню не дёргает камеру). */
function tryApplyPendingOrbitPivotOnDrag(ev: MouseEvent) {
  if (!rightMouseDown || !controls || orbitPivotAppliedThisGesture) return
  const dx = ev.clientX - rightMouseDownX
  const dy = ev.clientY - rightMouseDownY
  if (Math.hypot(dx, dy) < RIGHT_DRAG_THRESHOLD_PX) return
  rightMouseDragged = true
  if (pendingOrbitPivot) {
    applyOrbitPivotInvisibly(pendingOrbitPivot)
    syncTrackballMouseOnCircle(ev.pageX, ev.pageY)
    orbitPivotAppliedThisGesture = true
  }
  if (controls.noRotate) controls.noRotate = false
}

function onCanvasMouseMove(ev: MouseEvent) {
  updateMouseFromClient(ev.clientX, ev.clientY)
  hoverDirty = true
  if (placementActive.value) updatePlacementFromCursor(ev.clientX, ev.clientY)
  updateBoxSelectRectFromClient(ev.clientX, ev.clientY)
}

function onContainerMouseMove(ev: MouseEvent) {
  updateMouseFromClient(ev.clientX, ev.clientY)
  hoverDirty = true
}

function onControlsStart() {
  isCameraInteracting = true
  if (hoverTooltipEl) hoverTooltipEl.style.display = 'none'
  if (renderer) {
    renderer.setPixelRatio(Math.min(INTERACTION_PIXEL_RATIO, idlePixelRatio))
  }
}

function onControlsEnd() {
  isCameraInteracting = false
  hoverDirty = true
  rebuildSavedMeasurementsVisuals()
  updateCameraClipPlanes(true)
  if (renderer) {
    renderer.setPixelRatio(idlePixelRatio)
  }
}

const zoomToCursorPlane = new THREE.Plane()
const zoomToCursorPoint = new THREE.Vector3()
const zoomToCursorDir = new THREE.Vector3()
let zoomAnchorPoint: THREE.Vector3 | null = null
let lastWheelTime = 0

type TransformSnapshot = {
  modelId: string
  px: number
  py: number
  pz: number
  rx: number
  ry: number
  rz: number
}

type TransformUndoEntry = { modelId: string; before: TransformSnapshot; after: TransformSnapshot }

let draggedModelGroup: THREE.Group | null = null
let dragStartModelPos: THREE.Vector3 | null = null
let dragStartIntersection: THREE.Vector3 | null = null
/** Снимок до перетаскивания для отмены */
let dragMoveUndoBefore: TransformSnapshot | null = null
let draggedRotateWrapper: THREE.Group | null = null
let dragRotateLastClientX = 0
let dragRotateLastClientY = 0
/** Локальная точка pivot в родителе meshGroup — фиксируется в начале перетаскивания. */
let dragRotatePivotLocal: THREE.Vector3 | null = null
let dragRotateUndoBefore: TransformSnapshot | null = null
const MODEL_ROTATE_MOUSE_SENS = 0.005
/** Чтобы не считать клик после перетаскивания модели */
let didDragModel = false
/** Чтобы не считать клик измерения после перетаскивания выноса размера */
let didDragMeasurement = false
const dragPlane = new THREE.Plane()
const dragIntersect = new THREE.Vector3()

const UNDO_STACK_MAX = 80
const undoTransformStack: TransformUndoEntry[] = []
const redoTransformStack: TransformUndoEntry[] = []

let transformClipboard: TransformSnapshot | null = null

function getTransformSnapshot(wrapper: THREE.Group): TransformSnapshot {
  const modelId = String(wrapper.userData?.modelId ?? '')
  const e = wrapper.rotation
  return {
    modelId,
    px: wrapper.position.x,
    py: wrapper.position.y,
    pz: wrapper.position.z,
    rx: e.x,
    ry: e.y,
    rz: e.z,
  }
}

function transformsEqual(a: TransformSnapshot, b: TransformSnapshot): boolean {
  const e = 1e-6
  return (
    a.modelId === b.modelId &&
    Math.abs(a.px - b.px) < e &&
    Math.abs(a.py - b.py) < e &&
    Math.abs(a.pz - b.pz) < e &&
    Math.abs(a.rx - b.rx) < e &&
    Math.abs(a.ry - b.ry) < e &&
    Math.abs(a.rz - b.rz) < e
  )
}

function applyTransformSnapshot(s: TransformSnapshot) {
  const g = modelGroupsById.get(s.modelId)
  if (!g) return
  g.position.set(s.px, s.py, s.pz)
  g.rotation.set(s.rx, s.ry, s.rz)
  meshGroup?.updateMatrixWorld(true)
}

/** Точка привязки габарита в локальной СК модели (низ по Z — «на полу»). */
function getModelPlacementAnchorLocal(group: THREE.Group, bottomOnPlane = true): THREE.Vector3 {
  const saved = group.position.clone()
  group.position.set(0, 0, 0)
  group.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(group)
  const anchor = box.getCenter(new THREE.Vector3())
  if (bottomOnPlane) anchor.z = box.min.z
  group.position.copy(saved)
  group.updateMatrixWorld(true)
  return anchor
}

/** Первая модель в сцене: центр габарита в начале мировой СК. */
function anchorModelCenterAtWorldOrigin(group: THREE.Group) {
  group.position.set(0, 0, 0)
  group.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(group)
  if (box.isEmpty()) return
  const c = box.getCenter(new THREE.Vector3())
  group.position.set(-c.x, -c.y, -c.z)
  meshGroup?.updateMatrixWorld(true)
}

function placeModelAnchorAtWorld(group: THREE.Group, worldPoint: THREE.Vector3) {
  const offset = placementAnchorLocal.clone().applyQuaternion(group.quaternion)
  group.position.copy(worldPoint).sub(offset)
  meshGroup?.updateMatrixWorld(true)
}

function syncPlacementFieldsFromGroup(modelId: string) {
  const g = modelGroupsById.get(modelId)
  if (!g) return
  placementPosMm.value = {
    x: Math.round(g.position.x * 10) / 10,
    y: Math.round(g.position.y * 10) / 10,
    z: Math.round(g.position.z * 10) / 10,
  }
}

function pickPlacementPlanePoint(clientX: number, clientY: number): THREE.Vector3 | null {
  if (!camera || !renderer) return null
  const rect = renderer.domElement.getBoundingClientRect()
  const mx = ((clientX - rect.left) / rect.width) * 2 - 1
  const my = -((clientY - rect.top) / rect.height) * 2 + 1
  const r = new THREE.Raycaster()
  r.setFromCamera(new THREE.Vector2(mx, my), camera)
  placementPickPlane.normal.set(0, 0, 1)
  placementPickPlane.constant = -placementPickPlane.normal.dot(new THREE.Vector3(0, 0, 0))
  const hit = r.ray.intersectPlane(placementPickPlane, placementPickPoint)
  return hit ? placementPickPoint.clone() : null
}

function updatePlacementFromCursor(clientX: number, clientY: number) {
  const id = placementModelId.value
  const g = id ? modelGroupsById.get(id) : null
  if (!placementActive.value || !g) return
  const pt = pickPlacementPlanePoint(clientX, clientY)
  if (!pt) return
  placeModelAnchorAtWorld(g, pt)
  syncPlacementFieldsFromGroup(id!)
}

function applyPlacementFromFields() {
  const id = placementModelId.value
  const g = id ? modelGroupsById.get(id) : null
  if (!g) return
  const { x, y, z } = placementPosMm.value
  g.position.set(Number(x) || 0, Number(y) || 0, Number(z) || 0)
  meshGroup?.updateMatrixWorld(true)
}

function beginModelPlacement(modelId: string, opts?: { removeFromSceneOnCancel?: boolean }) {
  const g = modelGroupsById.get(modelId)
  if (!g || !meshGroup) return
  if (placementActive.value && placementModelId.value && placementModelId.value !== modelId) {
    cancelModelPlacement()
  }
  placementAnchorLocal = getModelPlacementAnchorLocal(g, true)
  placementCancelRemovesFromScene = opts?.removeFromSceneOnCancel ?? false
  placementModelId.value = modelId
  placementActive.value = true
  focusedModelId.value = modelId
  leftSidebarTab.value = 'tree'
  const name = loadedModels.value.find((m) => m.id === modelId)?.name ?? 'модель'
  placementStatusHint.value = `Размещение «${name}»: двигайте мышью, ЛКМ — зафиксировать, Esc — отмена.`
  syncPlacementFieldsFromGroup(modelId)
  meshGroup.updateMatrixWorld(true)
}

function confirmModelPlacement() {
  if (!placementActive.value || !placementModelId.value) return
  const id = placementModelId.value
  placementActive.value = false
  placementModelId.value = null
  placementStatusHint.value = ''
  placementCancelRemovesFromScene = false
  applyNavigationForFocusedModel()
  scheduleSceneMetricsRecalc()
  focusedModelId.value = id
}

function cancelModelPlacement() {
  if (!placementActive.value) return
  const id = placementModelId.value
  placementActive.value = false
  placementModelId.value = null
  placementStatusHint.value = ''
  if (id && placementCancelRemovesFromScene) {
    placementCancelRemovesFromScene = false
    setModelInScene(id, false)
    return
  }
  placementCancelRemovesFromScene = false
}

function afterModelAddedToScene(
  wrapper: THREE.Group,
  modelId: string,
  hadOtherModelsInScene: boolean,
  startPlacementIfNotFirst: boolean,
) {
  if (!hadOtherModelsInScene) {
    anchorModelCenterAtWorldOrigin(wrapper)
    return
  }
  if (startPlacementIfNotFirst) {
    beginModelPlacement(modelId, { removeFromSceneOnCancel: true })
  }
}

function pushTransformUndo(entry: TransformUndoEntry) {
  undoTransformStack.push(entry)
  if (undoTransformStack.length > UNDO_STACK_MAX) undoTransformStack.shift()
  redoTransformStack.length = 0
}

function afterTransformUndoRedo(modelId: string) {
  if (assemblyMates.value.length) reapplyAllAssemblyMates()
  else {
    meshGroup?.updateMatrixWorld(true)
    refreshSelectedMeasurementAfterTransform()
    rebuildSavedMeasurementsVisuals()
  }
}

function undoTransform(): boolean {
  const e = undoTransformStack.pop()
  if (!e) return false
  applyTransformSnapshot(e.before)
  redoTransformStack.push(e)
  afterTransformUndoRedo(e.modelId)
  return true
}

function redoTransform(): boolean {
  const e = redoTransformStack.pop()
  if (!e) return false
  applyTransformSnapshot(e.after)
  undoTransformStack.push(e)
  afterTransformUndoRedo(e.modelId)
  return true
}

function isModelPinned(modelId: string): boolean {
  return !!pinnedByModelId.value[modelId]
}

function togglePinFocusedModel() {
  const id = focusedModelId.value
  if (!id || !modelGroupsById.has(id)) return
  const next = !pinnedByModelId.value[id]
  pinnedByModelId.value = { ...pinnedByModelId.value, [id]: next }
}

function togglePinModelId(modelId: string) {
  if (!modelId || !modelGroupsById.has(modelId)) return
  const next = !pinnedByModelId.value[modelId]
  pinnedByModelId.value = { ...pinnedByModelId.value, [modelId]: next }
}

/** Вращение модели вокруг pivot по осям экрана (как поворот камеры: куда мышь — туда модель). */
function rotateWrapperAroundPivotScreenAxes(
  wrapper: THREE.Group,
  pivotLocal: THREE.Vector3,
  dxPx: number,
  dyPx: number,
  cam: THREE.Camera,
  orbitTarget: THREE.Vector3,
) {
  if (!wrapper.parent) return
  const eye = new THREE.Vector3().subVectors(cam.position, orbitTarget)
  if (eye.lengthSq() < 1e-12) return
  eye.normalize()
  const upRef = cam.up
  let right = new THREE.Vector3().crossVectors(eye, upRef)
  if (right.lengthSq() < 1e-12) right.set(1, 0, 0)
  else right.normalize()
  const screenUp = new THREE.Vector3().crossVectors(right, eye).normalize()
  const sens = MODEL_ROTATE_MOUSE_SENS
  const apply = (axis: THREE.Vector3, ang: number) => {
    if (ang === 0 || !Number.isFinite(ang)) return
    const q = new THREE.Quaternion().setFromAxisAngle(axis, ang)
    wrapper.position.sub(pivotLocal)
    wrapper.position.applyQuaternion(q)
    wrapper.position.add(pivotLocal)
    wrapper.quaternion.premultiply(q)
  }
  apply(screenUp, dxPx * sens)
  apply(right, dyPx * sens)
}

function copyFocusedTransform() {
  const id = focusedModelId.value
  if (!id) return
  const g = modelGroupsById.get(id)
  if (!g) return
  transformClipboard = getTransformSnapshot(g)
}

function pasteTransformToFocused() {
  if (!transformClipboard) return
  const id = focusedModelId.value
  if (!id) return
  const g = modelGroupsById.get(id)
  if (!g) return
  const before = getTransformSnapshot(g)
  const clip = transformClipboard
  g.position.set(clip.px, clip.py, clip.pz)
  g.rotation.set(clip.rx, clip.ry, clip.rz)
  meshGroup?.updateMatrixWorld(true)
  const after = getTransformSnapshot(g)
  if (!transformsEqual(before, after)) {
    pushTransformUndo({ modelId: id, before, after })
    afterTransformUndoRedo(id)
  }
}

function findWrapperGroup(obj: THREE.Object3D): THREE.Group | null {
  let o: THREE.Object3D | null = obj
  while (o && o.parent !== meshGroup) o = o.parent
  return o && o.parent === meshGroup ? (o as THREE.Group) : null
}

function findPartNodeInWrapper(obj: THREE.Object3D, wrapper: THREE.Group): THREE.Object3D | null {
  let o: THREE.Object3D | null = obj
  while (o && o !== wrapper) {
    if (o instanceof THREE.Mesh) return o
    o = o.parent
  }
  return obj instanceof THREE.Mesh ? obj : null
}

function normalizeComponentLabel(raw: string): string {
  const s = String(raw || '').trim()
  if (!s) return ''
  const noQty = s.replace(/\s*\(\d+\)\s*$/g, '')
  const noTailNum = noQty.replace(/([._-])\d{1,4}$/g, '')
  return noTailNum.replace(/\s{2,}/g, ' ').trim()
}

function inferComponentLabel(obj: THREE.Object3D): string {
  const direct = normalizeComponentLabel(String(obj.userData?.partName || obj.userData?.partId || obj.name || ''))
  if (direct && !/^(mesh|node|object|group)$/i.test(direct)) return direct
  let p: THREE.Object3D | null = obj.parent
  while (p) {
    const candidate = normalizeComponentLabel(String(p.name || ''))
    if (candidate && !/^(mesh|node|object|group|scene)$/i.test(candidate)) return candidate
    p = p.parent
  }
  return ''
}

function extractLabelsFromStepSpecMeta(meta: any): string[] {
  const sections = meta?.spec?.sections
  if (!sections || typeof sections !== 'object') return []
  const labels: string[] = []
  Object.values(sections).forEach((rows: any) => {
    if (!Array.isArray(rows)) return
    rows.forEach((r: any) => {
      const name = String(r?.name ?? '').trim()
      const des = String(r?.designation ?? '').trim()
      if (!name && !des) return
      labels.push(des ? `${name} [${des}]` : name)
    })
  })
  return [...new Set(labels)]
}

function labelsFromPartColorMeta(meta: PartColorMeta): string[] {
  const labels = meta.parts
    .map((p) => String(p.displayName || p.name || p.partId || '').trim())
    .filter(Boolean)
  return [...new Set(labels)]
}

/** STL — один меш; режем по несвязным телам и подписываем для дерева/цветов. */
function splitStlMergedMeshes(wrapper: THREE.Group, partMeta?: PartColorMeta | null): number {
  const labels = partMeta ? labelsFromPartColorMeta(partMeta) : []
  const toSplit: THREE.Mesh[] = []
  wrapper.children.forEach((c) => {
    if (c instanceof THREE.Mesh) toSplit.push(c)
  })
  if (!toSplit.length) return 0
  let created = 0
  for (const mesh of toSplit) {
    const parent = mesh.parent
    if (!parent) continue
    const split = splitMeshByConnectivity(mesh, labels)
    if (split.length <= 1) continue
    const oldVisible = mesh.visible
    parent.remove(mesh)
    mesh.geometry.dispose()
    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
    mats.forEach((m) => m.dispose())
    split.forEach((m) => {
      m.visible = oldVisible
      parent.add(m)
    })
    created += split.length
  }
  if (created > 1) {
    logger.info('Viewer3D', `STL: по связности выделено тел: ${created}`)
  }
  return created
}

function assignPartMetaToStlMeshes(wrapper: THREE.Object3D, meta: PartColorMeta): void {
  if (!meta.parts.length) return
  const meshes: THREE.Mesh[] = []
  wrapper.traverse((o) => {
    if (o instanceof THREE.Mesh) meshes.push(o)
  })
  meshes.sort((a, b) => meshVolumeScore(b) - meshVolumeScore(a))
  meshes.forEach((m, i) => {
    const part = meta.parts[i]
    if (!part) return
    const label = String(part.displayName || part.name || part.partId).trim()
    const hex = normalizeHexColor(part.defaultColor)
    m.name = label || m.name
    m.userData = {
      ...m.userData,
      partId: part.partId,
      partName: label,
      lockPartColor: !!hex,
      partColorHex: hex,
    }
  })
}

function splitMeshByConnectivity(
  mesh: THREE.Mesh,
  desiredLabels: string[] = []
): THREE.Mesh[] {
  const geom = mesh.geometry
  const pos = geom.getAttribute('position')
  if (!pos || pos.itemSize < 3 || pos.count < 3) return [mesh]
  const indexArray: number[] = []
  if (geom.index) {
    const src = geom.index.array as ArrayLike<number>
    for (let i = 0; i < src.length; i += 1) indexArray.push(Number(src[i]))
  } else {
    for (let i = 0; i < pos.count; i += 1) indexArray.push(i)
  }
  const triCount = Math.floor(indexArray.length / 3)
  if (triCount < 2) return [mesh]

  const vertToTris = new Map<number, number[]>()
  for (let t = 0; t < triCount; t += 1) {
    const a = indexArray[t * 3]
    const b = indexArray[t * 3 + 1]
    const c = indexArray[t * 3 + 2]
    ;[a, b, c].forEach((v) => {
      const arr = vertToTris.get(v)
      if (arr) arr.push(t)
      else vertToTris.set(v, [t])
    })
  }

  const visited = new Uint8Array(triCount)
  const triGroups: number[][] = []
  for (let start = 0; start < triCount; start += 1) {
    if (visited[start]) continue
    const queue = [start]
    visited[start] = 1
    const group: number[] = []
    while (queue.length > 0) {
      const t = queue.pop() as number
      group.push(t)
      const a = indexArray[t * 3]
      const b = indexArray[t * 3 + 1]
      const c = indexArray[t * 3 + 2]
      for (const v of [a, b, c]) {
        const neigh = vertToTris.get(v) || []
        for (const nt of neigh) {
          if (!visited[nt]) {
            visited[nt] = 1
            queue.push(nt)
          }
        }
      }
    }
    triGroups.push(group)
    if (triGroups.length > 1500) return [mesh]
  }
  if (triGroups.length <= 1) return [mesh]

  const srcPos = pos
  const created: THREE.Mesh[] = []
  triGroups
    .sort((a, b) => b.length - a.length)
    .forEach((tris, idx) => {
      const localIndex: number[] = []
      const vMap = new Map<number, number>()
      const localPos: number[] = []
      const mapVertex = (globalV: number) => {
        const prev = vMap.get(globalV)
        if (prev != null) return prev
        const next = vMap.size
        vMap.set(globalV, next)
        localPos.push(srcPos.getX(globalV), srcPos.getY(globalV), srcPos.getZ(globalV))
        return next
      }
      for (const t of tris) {
        const a = mapVertex(indexArray[t * 3])
        const b = mapVertex(indexArray[t * 3 + 1])
        const c = mapVertex(indexArray[t * 3 + 2])
        localIndex.push(a, b, c)
      }
      const g = new THREE.BufferGeometry()
      g.setAttribute('position', new THREE.Float32BufferAttribute(localPos, 3))
      g.setIndex(localIndex)
      g.computeVertexNormals()
      const m = new THREE.Mesh(g, Array.isArray(mesh.material) ? mesh.material.map((mm) => mm.clone()) : mesh.material.clone())
      m.position.copy(mesh.position)
      m.quaternion.copy(mesh.quaternion)
      m.scale.copy(mesh.scale)
      m.matrixAutoUpdate = mesh.matrixAutoUpdate
      m.visible = mesh.visible
      const label = desiredLabels[idx] || desiredLabels[desiredLabels.length - 1] || `Деталь ${idx + 1}`
      m.name = label
      m.userData = { ...mesh.userData, partName: label, splitFromMerged: true, splitIndex: idx }
      created.push(m)
    })
  return created.length > 1 ? created : [mesh]
}

function mergeMeshesIntoSingle(parent: THREE.Object3D, meshes: THREE.Mesh[], label: string): THREE.Mesh {
  const positions: number[] = []
  const indices: number[] = []
  let vOffset = 0
  const world = new THREE.Vector3()
  const local = new THREE.Vector3()
  meshes.forEach((mesh) => {
    const geom = mesh.geometry
    const pos = geom.getAttribute('position')
    if (!pos || pos.itemSize < 3) return
    const idxSrc = geom.index?.array as ArrayLike<number> | undefined
    for (let i = 0; i < pos.count; i += 1) {
      world.set(pos.getX(i), pos.getY(i), pos.getZ(i)).applyMatrix4(mesh.matrixWorld)
      local.copy(world)
      parent.worldToLocal(local)
      positions.push(local.x, local.y, local.z)
    }
    if (idxSrc) {
      for (let i = 0; i < idxSrc.length; i += 1) indices.push(Number(idxSrc[i]) + vOffset)
    } else {
      for (let i = 0; i < pos.count; i += 1) indices.push(i + vOffset)
    }
    vOffset += pos.count
  })
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  g.setIndex(indices)
  g.computeVertexNormals()
  const source = meshes[0]
  const mat = Array.isArray(source.material) ? source.material[0].clone() : source.material.clone()
  const out = new THREE.Mesh(g, mat)
  out.name = label
  out.userData = { ...source.userData, partName: label, mergedFromFragments: meshes.length }
  out.visible = meshes.some((m) => m.visible)
  return out
}

function reduceFragmentedPartsToSpecCount(parent: THREE.Object3D, parts: THREE.Mesh[], labels: string[]): THREE.Mesh[] {
  const meshSizeScore = (m: THREE.Mesh): number => {
    const sz = new THREE.Box3().setFromObject(m).getSize(new THREE.Vector3())
    return Math.max(1e-9, sz.x * sz.y * sz.z)
  }
  const mergePair = (a: THREE.Mesh, b: THREE.Mesh): THREE.Mesh => {
    const merged = mergeMeshesIntoSingle(parent, [a, b], a.name || b.name || 'Деталь')
    parent.remove(a)
    parent.remove(b)
    if (a.geometry) a.geometry.dispose()
    if (b.geometry) b.geometry.dispose()
    ;(Array.isArray(a.material) ? a.material : [a.material]).forEach((m) => m.dispose())
    ;(Array.isArray(b.material) ? b.material : [b.material]).forEach((m) => m.dispose())
    parent.add(merged)
    return merged
  }
  const closestIndex = (from: THREE.Mesh, arr: THREE.Mesh[]): number => {
    const c0 = new THREE.Box3().setFromObject(from).getCenter(new THREE.Vector3())
    let best = -1
    let bestD = Number.POSITIVE_INFINITY
    for (let i = 0; i < arr.length; i += 1) {
      if (arr[i] === from) continue
      const d = c0.distanceTo(new THREE.Box3().setFromObject(arr[i]).getCenter(new THREE.Vector3()))
      if (d < bestD) {
        bestD = d
        best = i
      }
    }
    return best
  }
  const expandedBox = (m: THREE.Mesh, pad: number) => new THREE.Box3().setFromObject(m).expandByScalar(pad)
  const nearOrIntersect = (a: THREE.Mesh, b: THREE.Mesh): boolean => {
    const ba = new THREE.Box3().setFromObject(a)
    const bb = new THREE.Box3().setFromObject(b)
    if (ba.intersectsBox(bb)) return true
    const sa = ba.getSize(new THREE.Vector3()).length()
    const sb = bb.getSize(new THREE.Vector3()).length()
    const pad = Math.max(0.2, Math.min(sa, sb) * 0.03)
    return expandedBox(a, pad).intersectsBox(expandedBox(b, pad))
  }

  const target = Math.min(labels.length, parts.length)
  if (target < 1 || parts.length <= target) return parts
  const work = [...parts]

  // Этап 0: склеиваем оболочки одной детали (тонкие полые профили),
  // если их bbox пересекаются или почти касаются.
  let mergedByTouch = true
  while (mergedByTouch && work.length > target) {
    mergedByTouch = false
    outer: for (let i = 0; i < work.length; i += 1) {
      for (let j = i + 1; j < work.length; j += 1) {
        if (!nearOrIntersect(work[i], work[j])) continue
        const merged = mergePair(work[i], work[j])
        const next = work.filter((_, idx) => idx !== i && idx !== j)
        next.push(merged)
        work.splice(0, work.length, ...next)
        mergedByTouch = true
        break outer
      }
    }
  }

  // Этап A: склеиваем микрофрагменты к ближайшим крупным, чтобы убрать "крошку".
  while (work.length > 2) {
    work.sort((a, b) => meshSizeScore(a) - meshSizeScore(b))
    const minScore = meshSizeScore(work[0])
    const maxScore = meshSizeScore(work[work.length - 1])
    const ratio = minScore / Math.max(1e-9, maxScore)
    if (ratio > 0.015) break
    const tiny = work[0]
    const j = closestIndex(tiny, work)
    if (j < 0) break
    const merged = mergePair(tiny, work[j])
    const filtered = work.filter((m, idx) => idx !== 0 && idx !== j)
    filtered.push(merged)
    work.splice(0, work.length, ...filtered)
  }

  const centerOf = (m: THREE.Mesh) => new THREE.Box3().setFromObject(m).getCenter(new THREE.Vector3())
  while (work.length > target) {
    let bestI = 0
    let bestJ = 1
    let bestD = Number.POSITIVE_INFINITY
    for (let i = 0; i < work.length; i += 1) {
      const ci = centerOf(work[i])
      for (let j = i + 1; j < work.length; j += 1) {
        const d = ci.distanceTo(centerOf(work[j]))
        if (d < bestD) {
          bestD = d
          bestI = i
          bestJ = j
        }
      }
    }
    const a = work[bestI]
    const b = work[bestJ]
    const merged = mergePair(a, b)
    const next: THREE.Mesh[] = []
    work.forEach((m, idx) => {
      if (idx !== bestI && idx !== bestJ) next.push(m)
    })
    next.push(merged)
    work.splice(0, work.length, ...next)
  }
  work.sort((x, y) => new THREE.Box3().setFromObject(y).getSize(new THREE.Vector3()).length()
    - new THREE.Box3().setFromObject(x).getSize(new THREE.Vector3()).length())
  work.forEach((m, idx) => {
    const label = labels[idx] || labels[labels.length - 1] || m.name || `Деталь ${idx + 1}`
    m.name = label
    m.userData = { ...m.userData, partName: label }
  })
  return work
}

function collectMeshes(root: THREE.Object3D): THREE.Mesh[] {
  const arr: THREE.Mesh[] = []
  root.traverse((o: THREE.Object3D) => { if (o instanceof THREE.Mesh) arr.push(o) })
  return arr
}

function meshVolumeScore(mesh: THREE.Mesh): number {
  const sz = new THREE.Box3().setFromObject(mesh).getSize(new THREE.Vector3())
  return Math.max(1e-9, sz.x * sz.y * sz.z)
}

function mergeTwoMeshesAtRoot(root: THREE.Object3D, a: THREE.Mesh, b: THREE.Mesh, label: string): THREE.Mesh {
  const positions: number[] = []
  const indices: number[] = []
  let vOffset = 0
  const world = new THREE.Vector3()
  const local = new THREE.Vector3()
  const appendMesh = (mesh: THREE.Mesh) => {
    const geom = mesh.geometry
    const pos = geom.getAttribute('position')
    if (!pos || pos.itemSize < 3) return
    const idxSrc = geom.index?.array as ArrayLike<number> | undefined
    for (let i = 0; i < pos.count; i += 1) {
      world.set(pos.getX(i), pos.getY(i), pos.getZ(i)).applyMatrix4(mesh.matrixWorld)
      local.copy(world)
      root.worldToLocal(local)
      positions.push(local.x, local.y, local.z)
    }
    if (idxSrc) {
      for (let i = 0; i < idxSrc.length; i += 1) indices.push(Number(idxSrc[i]) + vOffset)
    } else {
      for (let i = 0; i < pos.count; i += 1) indices.push(i + vOffset)
    }
    vOffset += pos.count
  }
  appendMesh(a)
  appendMesh(b)
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  g.setIndex(indices)
  g.computeVertexNormals()
  const mat = (Array.isArray(a.material) ? a.material[0] : a.material).clone()
  const out = new THREE.Mesh(g, mat)
  out.name = label
  out.userData = { ...a.userData, partName: label, mergedByAssemblyMap: true }
  ;[a, b].forEach((m) => {
    if (m.parent) m.parent.remove(m)
    if (m.geometry) m.geometry.dispose()
    ;(Array.isArray(m.material) ? m.material : [m.material]).forEach((mm) => mm.dispose())
  })
  root.add(out)
  return out
}

function applyAssemblyMapMatching(root: THREE.Object3D, assemblyMap: any): { matched: number; total: number } {
  const bom = Array.isArray(assemblyMap?.bom) ? assemblyMap.bom : []
  const labels = bom
    .map((b: any) => {
      const n = String(b?.name ?? '').trim()
      const d = String(b?.designation ?? '').trim()
      return n ? (d ? `${n} [${d}]` : n) : ''
    })
    .filter((x: string) => !!x)
  const meshes = collectMeshes(root)
  if (!labels.length || !meshes.length) return { matched: 0, total: meshes.length }

  let work = [...meshes]
  const target = Math.max(1, labels.length)
  while (work.length > target) {
    work.sort((x, y) => meshVolumeScore(x) - meshVolumeScore(y))
    const tiny = work[0]
    const c0 = new THREE.Box3().setFromObject(tiny).getCenter(new THREE.Vector3())
    let best = 1
    let bestD = Number.POSITIVE_INFINITY
    for (let i = 1; i < work.length; i += 1) {
      const d = c0.distanceTo(new THREE.Box3().setFromObject(work[i]).getCenter(new THREE.Vector3()))
      if (d < bestD) { bestD = d; best = i }
    }
    const merged = mergeTwoMeshesAtRoot(root, tiny, work[best], tiny.name || work[best].name || 'Деталь')
    const next = work.filter((_, idx) => idx !== 0 && idx !== best)
    next.push(merged)
    work = next
  }

  work.sort((a, b) => meshVolumeScore(b) - meshVolumeScore(a))
  work.forEach((m, i) => {
    const label = labels[i] || labels[labels.length - 1] || m.name || `Деталь ${i + 1}`
    const bomRow = bom[i]
    m.name = label
    m.userData = {
      ...m.userData,
      partName: label,
      partId: String(bomRow?.partId ?? `bom_${i + 1}`),
      instanceId: null,
      assemblyMapMatched: true,
    }
  })
  return { matched: Math.min(labels.length, work.length), total: work.length }
}

function splitMergedMeshesUsingSpec(root: THREE.Object3D, stepMetaPayload?: any): number {
  const labels = extractLabelsFromStepSpecMeta(stepMetaPayload)
  if (!labels.length) return 0
  let changed = 0
  root.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh)) return
    const parent = obj.parent
    if (!parent) return
    const split = splitMeshByConnectivity(obj, labels)
    if (split.length <= 1) return
    const reduced = reduceFragmentedPartsToSpecCount(parent, split, labels)
    const oldVisible = obj.visible
    parent.remove(obj)
    if (obj.geometry) obj.geometry.dispose()
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
    mats.forEach((m) => m.dispose())
    reduced.forEach((m) => {
      m.visible = oldVisible
      parent.add(m)
    })
    changed += reduced.length
  })
  return changed
}

function buildGeometryBucketsForMeshes(
  meshes: THREE.Mesh[],
  fallbackIndexStart: number,
): Map<
  string,
  {
    label: string
    categoryId: PartCategoryId
    ids: string[]
    visibleCount: number
    labelVotes: string[]
  }
> {
  const buckets = new Map<
    string,
    {
      label: string
      categoryId: PartCategoryId
      ids: string[]
      visibleCount: number
      labelVotes: string[]
    }
  >()
  meshes.forEach((obj, i) => {
    const inferred = inferComponentLabel(obj)
    const rawLabel = inferred || obj.name || `Деталь ${fallbackIndexStart + i + 1}`
    const groupKey = meshPartGroupKey(obj, rawLabel)
    const categoryId = inferPartCategory(rawLabel)
    const prev = buckets.get(groupKey)
    if (prev) {
      prev.ids.push(obj.uuid)
      if (obj.visible) prev.visibleCount += 1
      prev.labelVotes.push(rawLabel)
      return
    }
    buckets.set(groupKey, {
      label: rawLabel,
      categoryId,
      ids: [obj.uuid],
      visibleCount: obj.visible ? 1 : 0,
      labelVotes: [rawLabel],
    })
  })
  buckets.forEach((b) => {
    b.label = pickGeometryGroupLabel({ labels: b.labelVotes })
    b.categoryId = inferPartCategory(b.label)
  })
  return buckets
}

/** Плоский список групп деталей (имя как в модели, все экземпляры типа в одной строке). */
function bucketsToPartGroupNodes(
  modelId: string,
  buckets: Map<
    string,
    { label: string; categoryId: PartCategoryId; ids: string[]; visibleCount: number }
  >,
  idPrefix: string,
): ComponentTreeNode[] {
  return [...buckets.values()]
    .sort((a, b) => a.label.localeCompare(b.label, 'ru'))
    .map((g, idx) => ({
      id: `${modelId}:${idPrefix}grp:${idx}`,
      label: g.label,
      visible: g.visibleCount > 0,
      targetIds: g.ids,
      children: [],
      nodeKind: 'group' as const,
    }))
}

function findTreeNodeById(nodes: ComponentTreeNode[], rowId: string): ComponentTreeNode | null {
  for (const n of nodes) {
    if (n.id === rowId) return n
    const inChild = findTreeNodeById(n.children, rowId)
    if (inChild) return inChild
  }
  return null
}

function collectTargetIdsForTreeNode(modelId: string, rowId: string): string[] {
  const roots = componentTreeByModel.value[modelId]
  if (!roots) return []
  const node = findTreeNodeById(roots, rowId)
  if (!node) {
    const row = componentTreeRowsByModel.value[modelId]?.find((r) => r.id === rowId)
    return row?.targetIds ?? []
  }
  const ids: string[] = []
  const walk = (n: ComponentTreeNode) => {
    n.targetIds.forEach((id) => ids.push(id))
    n.children.forEach(walk)
  }
  walk(node)
  return [...new Set(ids)]
}

/** Дерево из иерархии GLB (STEP/XCAF сохраняет узлы сборки). */
function tryBuildTreeFromSceneHierarchy(modelId: string, wrapper: THREE.Group): ComponentTreeNode[] | null {
  const structural = wrapper.children.filter(
    (c) => !(c instanceof THREE.Mesh) && c.children.length > 0 && String(c.name || '').trim().length > 0,
  )
  if (structural.length === 0) return null

  const assemblyNodes: ComponentTreeNode[] = []
  for (let si = 0; si < structural.length; si++) {
    const branch = structural[si]
    const meshes: THREE.Mesh[] = []
    branch.traverse((o) => {
      if (o instanceof THREE.Mesh) meshes.push(o)
    })
    if (meshes.length === 0) continue
    const buckets = buildGeometryBucketsForMeshes(meshes, si * 1000)
    const partNodes = bucketsToPartGroupNodes(modelId, buckets, `s${si}:`)
    if (partNodes.length === 0) continue
    const branchLabel = String(branch.name).trim() || `Сборка ${si + 1}`
    assemblyNodes.push({
      id: `${modelId}:asm:${si}`,
      label: branchLabel,
      visible: partNodes.some((c) => c.visible),
      targetIds: [],
      children: partNodes,
      nodeKind: 'category',
    })
  }
  return assemblyNodes.length > 0 ? assemblyNodes : null
}

function buildComponentTreeForModel(modelId: string, wrapper: THREE.Group) {
  const hierarchyRoots = tryBuildTreeFromSceneHierarchy(modelId, wrapper)
  if (hierarchyRoots) {
    componentTreeByModel.value = { ...componentTreeByModel.value, [modelId]: hierarchyRoots }
    ensureExplodeCacheForModel(wrapper, true)
    if (explodeAmount.value > 0) applyExplodeForModel(wrapper, explodeAmount.value)
    return
  }

  const meshes: THREE.Mesh[] = []
  wrapper.traverse((obj) => {
    if (obj instanceof THREE.Mesh) meshes.push(obj)
  })
  const buckets = buildGeometryBucketsForMeshes(meshes, 0)
  const roots = bucketsToPartGroupNodes(modelId, buckets, '')
  componentTreeByModel.value = { ...componentTreeByModel.value, [modelId]: roots }
  ensureExplodeCacheForModel(wrapper, true)
  if (explodeAmount.value > 0) applyExplodeForModel(wrapper, explodeAmount.value)
}

function refreshComponentTreeVisibility(modelId: string) {
  const group = modelGroupsById.get(modelId)
  const tree = componentTreeByModel.value[modelId]
  if (!group || !tree) return
  const byId = new Map<string, boolean>()
  group.traverse((obj: THREE.Object3D) => byId.set(obj.uuid, obj.visible))
  const refreshNode = (n: ComponentTreeNode) => {
    if (n.targetIds.length > 0) {
      n.visible = n.targetIds.some((id) => byId.get(id) !== false)
    } else {
      n.visible = byId.get(n.id) ?? n.visible
    }
    n.children.forEach(refreshNode)
  }
  tree.forEach(refreshNode)
  componentTreeByModel.value = { ...componentTreeByModel.value, [modelId]: [...tree] }
}

function flattenComponentTree(nodes: ComponentTreeNode[], depth = 0): ComponentTreeRow[] {
  const rows: ComponentTreeRow[] = []
  nodes.forEach((n) => {
    rows.push({
      id: n.id,
      label: n.label,
      visible: n.visible,
      targetIds: n.targetIds,
      depth,
      nodeKind: n.nodeKind,
    })
    if (n.nodeKind === 'category' && !isCategoryExpandedForRow(n.id)) return
    rows.push(...flattenComponentTree(n.children, depth + 1))
  })
  return rows
}

function categoryExpandKeyFromRowId(modelId: string, rowId: string): string | null {
  const m = rowId.match(/^[^:]+:cat:(.+)$/)
  if (!m) return null
  return `${modelId}:${m[1]}`
}

function isCategoryExpandedForRow(rowId: string): boolean {
  const modelId = rowId.split(':')[0]
  const key = categoryExpandKeyFromRowId(modelId, rowId)
  if (!key) return true
  return expandedCategoryIds.value[key] !== false
}

function toggleCategoryExpanded(modelId: string, rowId: string) {
  const key = categoryExpandKeyFromRowId(modelId, rowId)
  if (!key) return
  expandedCategoryIds.value = {
    ...expandedCategoryIds.value,
    [key]: expandedCategoryIds.value[key] === false,
  }
}

function findMeshByUuid(uuid: string): THREE.Mesh | null {
  if (!meshGroup) return null
  let found: THREE.Mesh | null = null
  meshGroup.traverse((obj: THREE.Object3D) => {
    if (!found && obj instanceof THREE.Mesh && obj.uuid === uuid) found = obj
  })
  return found
}

function collectFocusedMeshIds(): Set<string> {
  const ids = new Set<string>()
  selectedPartRowKeys.value.forEach((key) => {
    const sep = key.indexOf(':')
    if (sep < 0) return
    const modelId = key.slice(0, sep)
    const rowId = key.slice(sep + 1)
    collectTargetIdsForTreeNode(modelId, rowId).forEach((id) => ids.add(id))
  })
  return ids
}

function clearPartFocusVisuals() {
  dimmedMeshBackups.forEach((backup, mesh) => {
    mesh.material = backup.material
    mesh.visible = backup.visible
  })
  dimmedMeshBackups.clear()
  partFocusActive.value = false
}

function applyPartFocusVisuals(focusedMeshIds: Set<string>) {
  clearPartFocusVisuals()
  if (!partIsolateDimOthers.value || !meshGroup || focusedMeshIds.size === 0) return
  let dimmed = 0
  const maxDim = 800
  meshGroup.traverse((obj: THREE.Object3D) => {
    if (dimmed >= maxDim) return
    if (!(obj instanceof THREE.Mesh) || !obj.visible || focusedMeshIds.has(obj.uuid)) return
    if (!obj.material) return
    dimmedMeshBackups.set(obj, { material: obj.material, visible: obj.visible })
    obj.material = sharedGhostMaterial
    dimmed += 1
  })
  partFocusActive.value = dimmed > 0
}

function getBboxForMeshIds(ids: Set<string>): THREE.Box3 | null {
  const box = new THREE.Box3()
  let any = false
  ids.forEach((uuid) => {
    const mesh = findMeshByUuid(uuid)
    if (!mesh?.visible) return
    mesh.updateMatrixWorld(true)
    const b = new THREE.Box3().setFromObject(mesh)
    if (!b.isEmpty()) {
      box.union(b)
      any = true
    }
  })
  return any ? box : null
}

function focusCameraOnMeshIds(ids: Set<string>) {
  if (!camera || !controls || ids.size === 0) return
  const box = getBboxForMeshIds(ids)
  if (!box || box.isEmpty()) return
  const center = box.getCenter(new THREE.Vector3())
  const size = box.getSize(new THREE.Vector3())
  const maxDim = Math.max(size.x, size.y, size.z, 1)
  const direction = camera.position.clone().sub(controls.target)
  if (direction.lengthSq() < 1e-8) direction.set(1, 0.75, 1)
  direction.normalize()
  camera.position.copy(center).add(direction.multiplyScalar(maxDim * 1.65))
  controls.target.copy(center)
  controls.update()
}

function applySelectionHighlightToMesh(mesh: THREE.Mesh) {
  if (!mesh.material) return
  const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
  const backups: SelectionMaterialBackup[] = []
  mats.forEach((mat) => {
    if (!('color' in mat)) return
    const m = mat as THREE.MeshPhongMaterial & { emissive?: THREE.Color; emissiveIntensity?: number }
    backups.push({
      color: m.color.clone(),
      emissive: m.emissive?.clone() ?? new THREE.Color(0x000000),
      emissiveIntensity: typeof m.emissiveIntensity === 'number' ? m.emissiveIntensity : 1,
    })
    const highlighted = m.color.clone()
    highlighted.lerp(PART_SELECTION_TINT, 0.48)
    highlighted.r = Math.min(1, highlighted.r * 1.55)
    highlighted.g = Math.min(1, highlighted.g * 1.55)
    highlighted.b = Math.min(1, highlighted.b * 1.65)
    m.color.copy(highlighted)
    if (m.emissive) {
      m.emissive.setHex(PART_SELECTION_EMISSIVE)
      if (typeof m.emissiveIntensity === 'number') {
        m.emissiveIntensity = PART_SELECTION_EMISSIVE_INTENSITY
      }
    }
  })
  if (backups.length > 0) {
    selectionMaterialBackups.set(mesh, backups)
    highlightedComponentMeshes.add(mesh)
  }
}

function applySelectionVisualsAndFocus() {
  clearComponentHighlight()
  const focusedIds = collectFocusedMeshIds()
  if (focusedIds.size === 0) {
    clearPartFocusVisuals()
    selectedComponentRowId.value = null
    return
  }
  if (!meshGroup) return
  meshGroup.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh) || !obj.visible || !focusedIds.has(obj.uuid)) return
    applySelectionHighlightToMesh(obj)
  })
  if (partIsolateDimOthers.value) applyPartFocusVisuals(focusedIds)
}

function restorePartTreeIsolate() {
  const st = partTreeIsolateState.value
  if (!st) return
  const g = modelGroupsById.get(st.modelId)
  if (g) {
    g.traverse((obj: THREE.Object3D) => {
      if (!(obj instanceof THREE.Mesh)) return
      const prev = st.meshVisible.get(obj.uuid)
      if (prev !== undefined) obj.visible = prev
      restoreMeshRaycast(obj)
    })
    refreshComponentTreeVisibility(st.modelId)
  }
  partTreeIsolateState.value = null
  scheduleSceneMetricsRecalc()
}

function isolatePartFromTree(modelId: string, rowId: string) {
  const row = componentTreeRowsByModel.value[modelId]?.find((r) => r.id === rowId)
  if (row?.nodeKind === 'category') return

  if (partTreeIsolateState.value?.modelId === modelId && partTreeIsolateState.value?.rowId === rowId) {
    restorePartTreeIsolate()
    selectedPartRowKeys.value = new Set()
    selectedComponentRowId.value = null
    clearPartFocusVisuals()
    clearComponentHighlight()
    return
  }

  restorePartTreeIsolate()

  const keepIds = new Set(collectTargetIdsForTreeNode(modelId, rowId))
  if (keepIds.size === 0) return
  const g = modelGroupsById.get(modelId)
  if (!g) return

  const meshVisible = new Map<string, boolean>()
  g.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh)) return
    meshVisible.set(obj.uuid, obj.visible)
    obj.visible = keepIds.has(obj.uuid)
  })

  partTreeIsolateState.value = { modelId, rowId, meshVisible, keepIds }
  applyIsolateRaycastBlocks(modelId, keepIds)
  focusedModelId.value = modelId
  expandedModelIds.value = { ...expandedModelIds.value, [modelId]: true }

  const key = `${modelId}:${rowId}`
  selectedPartRowKeys.value = new Set([key])
  selectedComponentRowId.value = key
  clearPartFocusVisuals()
  clearComponentHighlight()
  applySelectionVisualsAndFocus()

  focusCameraOnMeshIds(keepIds)
  refreshComponentTreeVisibility(modelId)
  scheduleSceneMetricsRecalc()
}

function resetPartSelectionAndView() {
  restorePartTreeIsolate()
  selectedPartRowKeys.value = new Set()
  selectedComponentRowId.value = null
  clearPartFocusVisuals()
  clearComponentHighlight()
}

function restoreOriginalModelColors(modelId?: string) {
  resetPartSelectionAndView()
  layerColorOverrideByUuid.value = {}
  const groups = modelId
    ? [modelGroupsById.get(modelId)].filter((g): g is THREE.Group => !!g)
    : [...modelGroupsById.values()]
  for (const g of groups) {
    g.traverse((obj: THREE.Object3D) => {
      if (!(obj instanceof THREE.Mesh) || !obj.material) return
      const hex = normalizeHexColor(String(obj.userData?.partColorHex ?? ''))
      if (hex) applyHexToMesh(obj, hex)
    })
    finalizeModelPartColors(g, null)
  }
  applyShadingMode()
}

function isPartBoxSelectEnabled(): boolean {
  if (measureModeRef.value || modelRotateMode.value || placementActive.value) return false
  if (remarkAnchorPickMode.value || assemblyPickTarget.value || sectionModeRef.value) return false
  if (cadLinearPickTarget.value && measureTypeRef.value === 'cad-linear') return false
  return !!(meshGroup?.children.length)
}

function updateBoxSelectRectFromClient(clientX: number, clientY: number) {
  if (!boxSelectDrag || !renderer) return
  const rect = renderer.domElement.getBoundingClientRect()
  const x0 = boxSelectDrag.startX - rect.left
  const y0 = boxSelectDrag.startY - rect.top
  const x1 = clientX - rect.left
  const y1 = clientY - rect.top
  const mode: 'window' | 'crossing' = x1 >= x0 ? 'window' : 'crossing'
  boxSelectRect.value = {
    left: Math.min(x0, x1),
    top: Math.min(y0, y1),
    width: Math.abs(x1 - x0),
    height: Math.abs(y1 - y0),
    mode,
  }
}

function onBoxSelectWindowMove(ev: MouseEvent) {
  updateBoxSelectRectFromClient(ev.clientX, ev.clientY)
}

function onBoxSelectWindowUp(ev: MouseEvent) {
  if (ev.button !== 0 || !boxSelectDrag) return
  finishBoxSelect(ev.clientX, ev.clientY)
}

function attachBoxSelectWindowListeners() {
  window.addEventListener('mousemove', onBoxSelectWindowMove, true)
  window.addEventListener('mouseup', onBoxSelectWindowUp, true)
}

function detachBoxSelectWindowListeners() {
  window.removeEventListener('mousemove', onBoxSelectWindowMove, true)
  window.removeEventListener('mouseup', onBoxSelectWindowUp, true)
}

function beginBoxSelectDrag(ev: MouseEvent) {
  boxSelectDrag = {
    startX: ev.clientX,
    startY: ev.clientY,
    additive: !!(ev.ctrlKey || ev.metaKey || ev.shiftKey),
  }
  attachBoxSelectWindowListeners()
  if (controls) controls.enabled = false
  ev.preventDefault()
  ev.stopPropagation()
}

function meshScreenRect(mesh: THREE.Mesh, canvasRect: DOMRect): { minX: number; minY: number; maxX: number; maxY: number } | null {
  if (!camera) return null
  mesh.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(mesh)
  if (box.isEmpty()) return null
  const corners = [
    new THREE.Vector3(box.min.x, box.min.y, box.min.z),
    new THREE.Vector3(box.min.x, box.min.y, box.max.z),
    new THREE.Vector3(box.min.x, box.max.y, box.min.z),
    new THREE.Vector3(box.min.x, box.max.y, box.max.z),
    new THREE.Vector3(box.max.x, box.min.y, box.min.z),
    new THREE.Vector3(box.max.x, box.min.y, box.max.z),
    new THREE.Vector3(box.max.x, box.max.y, box.min.z),
    new THREE.Vector3(box.max.x, box.max.y, box.max.z),
  ]
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  const v = new THREE.Vector3()
  for (const c of corners) {
    v.copy(c).project(camera)
    const sx = ((v.x + 1) / 2) * canvasRect.width
    const sy = ((-v.y + 1) / 2) * canvasRect.height
    minX = Math.min(minX, sx)
    minY = Math.min(minY, sy)
    maxX = Math.max(maxX, sx)
    maxY = Math.max(maxY, sy)
  }
  if (!Number.isFinite(minX)) return null
  return { minX, minY, maxX, maxY }
}

function rectFullyInside(a: { minX: number; minY: number; maxX: number; maxY: number }, sel: { left: number; top: number; right: number; bottom: number }) {
  return a.minX >= sel.left && a.maxX <= sel.right && a.minY >= sel.top && a.maxY <= sel.bottom
}

function rectIntersects(a: { minX: number; minY: number; maxX: number; maxY: number }, sel: { left: number; top: number; right: number; bottom: number }) {
  return !(a.maxX < sel.left || a.minX > sel.right || a.maxY < sel.top || a.minY > sel.bottom)
}

function finishBoxSelect(clientX: number, clientY: number) {
  detachBoxSelectWindowListeners()
  if (!renderer || !boxSelectDrag) return
  const rect = renderer.domElement.getBoundingClientRect()
  const x0 = boxSelectDrag.startX - rect.left
  const y0 = boxSelectDrag.startY - rect.top
  const x1 = clientX - rect.left
  const y1 = clientY - rect.top
  const mode: 'window' | 'crossing' = x1 >= x0 ? 'window' : 'crossing'
  const sel = {
    left: Math.min(x0, x1),
    top: Math.min(y0, y1),
    right: Math.max(x0, x1),
    bottom: Math.max(y0, y1),
  }
  if (Math.abs(x1 - x0) < 4 && Math.abs(y1 - y0) < 4) {
    boxSelectDrag = null
    boxSelectRect.value = null
    if (controls) controls.enabled = true
    return
  }
  didBoxSelect = true
  const next = boxSelectDrag.additive ? new Set(selectedPartRowKeys.value) : new Set<string>()
  Object.entries(componentTreeRowsByModel.value).forEach(([modelId, rows]) => {
    rows.forEach((row) => {
      if (row.nodeKind === 'category' || !row.targetIds.length) return
      let matched = false
      for (const uuid of row.targetIds) {
        const mesh = findMeshByUuid(uuid)
        if (!mesh?.visible) continue
        const mb = meshScreenRect(mesh, rect)
        if (!mb) continue
        const ok = mode === 'window' ? rectFullyInside(mb, sel) : rectIntersects(mb, sel)
        if (ok) {
          matched = true
          break
        }
      }
      if (matched) next.add(`${modelId}:${row.id}`)
    })
  })
  selectedPartRowKeys.value = next
  const first = next.values().next().value
  selectedComponentRowId.value = first ?? null
  applySelectionVisualsAndFocus()
  if (next.size > 0) focusCameraOnMeshIds(collectFocusedMeshIds())
  boxSelectDrag = null
  boxSelectRect.value = null
  if (controls) controls.enabled = true
}

function assignSelectedPartsToLayer(layerId: string) {
  if (!layerId || selectedPartRowKeys.value.size === 0) return
  const nextLayer = { ...meshLayerByUuid.value }
  selectedPartRowKeys.value.forEach((key) => {
    const sep = key.indexOf(':')
    if (sep < 0) return
    const modelId = key.slice(0, sep)
    const rowId = key.slice(sep + 1)
    const row = componentTreeRowsByModel.value[modelId]?.find((r) => r.id === rowId)
    row?.targetIds.forEach((uuid) => {
      nextLayer[uuid] = layerId
    })
  })
  meshLayerByUuid.value = nextLayer
}

function applyLayerColorToSelected(hex: string) {
  if (!hex || selectedPartRowKeys.value.size === 0) return
  const next = { ...layerColorOverrideByUuid.value }
  selectedPartRowKeys.value.forEach((key) => {
    const sep = key.indexOf(':')
    if (sep < 0) return
    const modelId = key.slice(0, sep)
    const rowId = key.slice(sep + 1)
    const row = componentTreeRowsByModel.value[modelId]?.find((r) => r.id === rowId)
    row?.targetIds.forEach((uuid) => {
      next[uuid] = hex
      const mesh = findMeshByUuid(uuid)
      if (mesh?.material && 'color' in mesh.material) {
        ;(mesh.material as THREE.MeshPhongMaterial).color.set(hex)
      }
    })
  })
  layerColorOverrideByUuid.value = next
}

function addSceneLayer3d() {
  const n = sceneLayers3d.value.length
  const id = `layer-${Date.now()}`
  sceneLayers3d.value = [
    ...sceneLayers3d.value,
    { id, name: `${n} — Слой ${n}`, color: '#c8d4e8', visible: true },
  ]
}

function toggleSceneLayerVisibility(layerId: string) {
  sceneLayers3d.value = sceneLayers3d.value.map((l) =>
    l.id === layerId ? { ...l, visible: !l.visible } : l,
  )
  applySceneLayerVisibility()
}

function applySceneLayerVisibility() {
  if (!meshGroup) return
  const hiddenLayers = new Set(sceneLayers3d.value.filter((l) => !l.visible).map((l) => l.id))
  meshGroup.traverse((obj: THREE.Object3D) => {
    if (!(obj instanceof THREE.Mesh)) return
    const layerId = meshLayerByUuid.value[obj.uuid] ?? 'layer-0'
    if (hiddenLayers.has(layerId)) obj.visible = false
  })
  refreshAllComponentTreeVisibility()
}

function refreshAllComponentTreeVisibility() {
  Object.keys(componentTreeByModel.value).forEach((modelId) => refreshComponentTreeVisibility(modelId))
}

const selectedPartsSummary = computed(() => {
  const n = selectedPartRowKeys.value.size
  if (n === 0) return 'Нет выбранных деталей'
  return `Выбрано групп деталей: ${n}`
})

const componentTreeRowsByModel = computed<Record<string, ComponentTreeRow[]>>(() => {
  const out: Record<string, ComponentTreeRow[]> = {}
  Object.entries(componentTreeByModel.value).forEach(([modelId, nodes]) => {
    out[modelId] = flattenComponentTree(nodes)
  })
  return out
})

const focusedComponentTreeRows = computed(() => {
  const id = focusedModelId.value
  if (!id) return []
  return componentTreeRowsByModel.value[id] ?? []
})

const focusedModelForTree = computed(() => {
  const id = focusedModelId.value
  if (!id) return null
  return loadedModels.value.find((m) => m.id === id) ?? null
})

function toggleComponentVisibility(modelId: string, rowId: string) {
  const row = componentTreeRowsByModel.value[modelId]?.find((r) => r.id === rowId)
  if (!row?.targetIds.length) return
  setComponentVisibilityByRow(modelId, rowId, !row.visible)
}

function setComponentVisibilityByRow(modelId: string, rowId: string, visible: boolean) {
  const group = modelGroupsById.get(modelId)
  const row = componentTreeRowsByModel.value[modelId]?.find((r) => r.id === rowId)
  if (!group || !row?.targetIds.length) return
  const targetSet = new Set(row.targetIds)
  group.traverse((obj: THREE.Object3D) => {
    if (targetSet.has(obj.uuid)) obj.visible = visible
  })
  syncOverlayVisibilityForModel(modelId)
  clearHiddenOutlinesForModel(modelId)
  refreshComponentTreeVisibility(modelId)
  if (!visible && selectedPartRowKeys.value.has(`${modelId}:${rowId}`)) {
    const next = new Set(selectedPartRowKeys.value)
    next.delete(`${modelId}:${rowId}`)
    selectedPartRowKeys.value = next
    applySelectionVisualsAndFocus()
  } else if (visible && selectedPartRowKeys.value.has(`${modelId}:${rowId}`)) {
    selectComponentRow(modelId, rowId)
  }
  scheduleSceneMetricsRecalc()
}

function setComponentVisibilityForObject(modelId: string, obj: THREE.Object3D, visible: boolean) {
  const mesh = obj instanceof THREE.Mesh ? obj : null
  if (mesh) {
    const row = findPartRowForMeshUuid(modelId, mesh.uuid)
    if (row?.targetIds.length) {
      setComponentVisibilityByRow(modelId, row.id, visible)
      return
    }
  }
  setSingleComponentVisibility(modelId, obj, visible)
}

function setSingleComponentVisibility(modelId: string, obj: THREE.Object3D, visible: boolean) {
  obj.visible = visible
  syncOverlayVisibilityForModel(modelId)
  clearHiddenOutlinesForModel(modelId)
  refreshComponentTreeVisibility(modelId)
  scheduleSceneMetricsRecalc()
}

function clearComponentHighlight() {
  highlightedComponentMeshes.forEach((mesh) => {
    const backups = selectionMaterialBackups.get(mesh)
    if (!backups?.length || !mesh.material) return
    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
    mats.forEach((mat, index) => {
      const backup = backups[index]
      if (!backup || !('color' in mat)) return
      const m = mat as THREE.MeshPhongMaterial & { emissive?: THREE.Color; emissiveIntensity?: number }
      m.color.copy(backup.color)
      if (m.emissive) m.emissive.copy(backup.emissive)
      if (typeof m.emissiveIntensity === 'number') m.emissiveIntensity = backup.emissiveIntensity
    })
  })
  highlightedComponentMeshes.clear()
  selectionMaterialBackups.clear()
}

function findPartRowForMeshUuid(modelId: string, meshUuid: string): ComponentTreeRow | null {
  const rows = componentTreeRowsByModel.value[modelId] ?? []
  for (const row of rows) {
    if (row.nodeKind === 'category') continue
    if (row.targetIds.includes(meshUuid)) return row
  }
  return null
}

function selectComponentRow(modelId: string, rowId: string, ev?: MouseEvent) {
  const row = componentTreeRowsByModel.value[modelId]?.find((r) => r.id === rowId)
  if (row?.nodeKind === 'category') {
    toggleCategoryExpanded(modelId, rowId)
    return
  }
  const key = `${modelId}:${rowId}`
  const additive = !!(ev?.ctrlKey || ev?.metaKey || ev?.shiftKey)
  const next = additive ? new Set(selectedPartRowKeys.value) : new Set<string>()
  if (additive && next.has(key)) next.delete(key)
  else next.add(key)
  selectedPartRowKeys.value = next
  selectedComponentRowId.value = next.size === 1 ? key : next.has(key) ? key : [...next][0] ?? null
  applySelectionVisualsAndFocus()
}

function selectComponentRowAndFocus(modelId: string, rowId: string) {
  isolatePartFromTree(modelId, rowId)
}

function isModelExpanded(modelId: string): boolean {
  if (expandedModelIds.value[modelId] === true) return true
  if (expandedModelIds.value[modelId] === false) return false
  return focusedModelId.value === modelId
}

function toggleModelExpanded(modelId: string) {
  expandedModelIds.value = { ...expandedModelIds.value, [modelId]: !isModelExpanded(modelId) }
}

function modelPartsAnyVisible(modelId: string): boolean {
  const rows = componentTreeRowsByModel.value[modelId]
  if (!rows?.length) {
    const g = modelGroupsById.get(modelId)
    if (!g) return false
    let any = false
    g.traverse((obj: THREE.Object3D) => {
      if (any || !(obj instanceof THREE.Mesh)) return
      if (obj.visible) any = true
    })
    return any
  }
  return rows.some((r) => r.visible)
}

function toggleModelPartsVisibility(modelId: string) {
  const group = modelGroupsById.get(modelId)
  if (!group) return
  const item = loadedModels.value.find((m) => m.id === modelId)
  if (item && !item.inScene) {
    setModelInScene(modelId, true)
    return
  }
  const nextVisible = !modelPartsAnyVisible(modelId)
  group.traverse((obj: THREE.Object3D) => {
    if (obj instanceof THREE.Mesh) obj.visible = nextVisible
  })
  syncOverlayVisibilityForModel(modelId)
  clearHiddenOutlinesForModel(modelId)
  refreshComponentTreeVisibility(modelId)
  if (!nextVisible) clearComponentHighlight()
  scheduleSceneMetricsRecalc()
}

function onModelTreeHeaderClick(item: { id: string; inScene: boolean }) {
  focusedModelId.value = item.id
  expandedModelIds.value = { ...expandedModelIds.value, [item.id]: true }
  if (!item.inScene) setModelInScene(item.id, true)
  else applyNavigationForFocusedModel()
}

function onModelTreeHeaderDblClick(item: { id: string; inScene: boolean }) {
  onModelTreeHeaderClick(item)
  focusModelInView()
}

function modelTreeRows(modelId: string): ComponentTreeRow[] {
  return componentTreeRowsByModel.value[modelId] ?? []
}

function disposeAssemblyHighlightGroupMeshes() {
  if (!assemblyHighlightGroup) return
  while (assemblyHighlightGroup.children.length > 0) {
    const c = assemblyHighlightGroup.children[0] as THREE.Mesh
    assemblyHighlightGroup.remove(c)
    c.geometry?.dispose()
    const m = c.material
    if (Array.isArray(m)) m.forEach((x) => x.dispose())
    else if (m) m.dispose()
  }
}

function disposePlanePreviewGeometry(p: AssemblyPlaneSelection | null | undefined) {
  if (!p) return
  p.previewGeometry?.dispose()
  p.previewGeometry = undefined
}

function stripStaleAssemblyFaceTriangles() {
  disposePlanePreviewGeometry(assemblySourcePlane.value ?? undefined)
  disposePlanePreviewGeometry(assemblyTargetPlane.value ?? undefined)
  disposePlanePreviewGeometry(assemblySymBase1.value ?? undefined)
  disposePlanePreviewGeometry(assemblySymBase2.value ?? undefined)
  disposePlanePreviewGeometry(assemblySymPart1.value ?? undefined)
  disposePlanePreviewGeometry(assemblySymPart2.value ?? undefined)
}

const MESH_PATCH_MAX_TRIS = 1400
const PLANAR_NORMAL_MAX_DEV = 0.055
const CYLINDER_AXIS_MAX_DOT = 0.14

function meshTriangleWorldNormal(mesh: THREE.Mesh, triIndex: number): THREE.Vector3 | null {
  const geom = mesh.geometry as THREE.BufferGeometry
  const pos = geom.attributes.position as THREE.BufferAttribute | undefined
  if (!pos) return null
  const index = geom.index
  const ia = index ? index.getX(triIndex * 3) : triIndex * 3
  const ib = index ? index.getX(triIndex * 3 + 1) : triIndex * 3 + 1
  const ic = index ? index.getX(triIndex * 3 + 2) : triIndex * 3 + 2
  const va = new THREE.Vector3(pos.getX(ia), pos.getY(ia), pos.getZ(ia))
  const vb = new THREE.Vector3(pos.getX(ib), pos.getY(ib), pos.getZ(ib))
  const vc = new THREE.Vector3(pos.getX(ic), pos.getY(ic), pos.getZ(ic))
  return new THREE.Vector3()
    .crossVectors(vb.clone().sub(va), vc.clone().sub(va))
    .transformDirection(mesh.matrixWorld)
    .normalize()
}

function buildMeshFaceAdjacency(mesh: THREE.Mesh): Map<string, number[]> {
  const geom = mesh.geometry as THREE.BufferGeometry
  const index = geom.index
  const triCount = index ? index.count / 3 : (geom.attributes.position as THREE.BufferAttribute).count / 3
  const edgeToTris = new Map<string, number[]>()
  const edgeKey = (a: number, b: number) => (a < b ? `${a}_${b}` : `${b}_${a}`)
  const triVert = (ti: number, corner: number) => (index ? index.getX(ti * 3 + corner) : ti * 3 + corner)
  for (let ti = 0; ti < triCount; ti++) {
    const a = triVert(ti, 0)
    const b = triVert(ti, 1)
    const c = triVert(ti, 2)
    for (const [u, v] of [
      [a, b],
      [b, c],
      [c, a],
    ] as [number, number][]) {
      const k = edgeKey(u, v)
      const list = edgeToTris.get(k) ?? []
      list.push(ti)
      edgeToTris.set(k, list)
    }
  }
  const adj = new Map<number, number[]>()
  for (const tris of edgeToTris.values()) {
    if (tris.length !== 2) continue
    const [t0, t1] = tris
    const l0 = adj.get(t0) ?? []
    l0.push(t1)
    adj.set(t0, l0)
    const l1 = adj.get(t1) ?? []
    l1.push(t0)
    adj.set(t1, l1)
  }
  return adj
}

function analyzeMeshSurfaceFromHit(
  hit: THREE.Intersection,
  wrapper: THREE.Group,
): {
  kind: MeshFaceSurfaceKind
  normalWorld: THREE.Vector3
  normalLocal: THREE.Vector3
  cylinderAxisLocal?: THREE.Vector3
} | null {
  const mesh = hit.object as THREE.Mesh
  if (!mesh.geometry || hit.faceIndex === undefined) return null
  const startTri = hit.faceIndex
  const adj = buildMeshFaceAdjacency(mesh)
  const normals: THREE.Vector3[] = []
  const queue = [startTri]
  const seen = new Set<number>([startTri])
  while (queue.length > 0 && normals.length < MESH_PATCH_MAX_TRIS) {
    const ti = queue.pop()!
    const n = meshTriangleWorldNormal(mesh, ti)
    if (n) normals.push(n)
    const nb = adj.get(ti) ?? []
    for (const nt of nb) {
      if (seen.has(nt)) continue
      seen.add(nt)
      queue.push(nt)
    }
  }
  if (normals.length === 0) return null
  const avg = new THREE.Vector3()
  normals.forEach((n) => avg.add(n))
  if (avg.lengthSq() < 1e-12) return null
  avg.normalize()
  let maxDev = 0
  for (const n of normals) {
    maxDev = Math.max(maxDev, 1 - Math.abs(n.dot(avg)))
  }
  const normalWorld = avg.clone()
  const normalLocal = worldNormalToModelLocal(wrapper, normalWorld)
  if (maxDev <= PLANAR_NORMAL_MAX_DEV) {
    return { kind: 'plane', normalWorld, normalLocal }
  }
  let bestAxis: THREE.Vector3 | null = null
  let bestScore = Infinity
  for (let i = 0; i < Math.min(normals.length, 48); i++) {
    for (let j = i + 1; j < Math.min(normals.length, 48); j++) {
      const c = new THREE.Vector3().crossVectors(normals[i], normals[j])
      if (c.lengthSq() < 0.02) continue
      c.normalize()
      let s = 0
      for (const n of normals) s += Math.abs(n.dot(c))
      const score = s / normals.length
      if (score < bestScore) {
        bestScore = score
        bestAxis = c.clone()
      }
    }
  }
  if (bestAxis && bestScore <= CYLINDER_AXIS_MAX_DOT) {
    const cylinderAxisLocal = worldNormalToModelLocal(wrapper, bestAxis)
    return { kind: 'cylinder', normalWorld, normalLocal, cylinderAxisLocal }
  }
  return { kind: 'unknown', normalWorld, normalLocal }
}

function assemblyPickRequiresPlanarSurface(): boolean {
  if (assemblyMateType.value === 'coord') return true
  if (assemblyMateType.value === 'symmetric') return true
  return assemblyMateType.value === 'plane' || assemblyMateType.value === 'distance'
}

function buildAssemblyPlaneFromHit(
  hit: THREE.Intersection,
  wrapper: THREE.Group,
  modelId: string,
): { pick: AssemblyPlaneSelection | null; error?: string } {
  const face = hit.face
  if (!face) return { pick: null, error: 'Грань не определена.' }
  const analysis = analyzeMeshSurfaceFromHit(hit, wrapper)
  if (!analysis) return { pick: null, error: 'Не удалось проанализировать грань.' }
  if (assemblyPickRequiresPlanarSurface()) {
    if (analysis.kind === 'cylinder') {
      return {
        pick: null,
        error:
          'Цилиндрическая поверхность: для совмещения плоскостей выберите плоскую грань. Сопряжение осей цилиндров будет добавлено отдельно.',
      }
    }
    if (analysis.kind !== 'plane') {
      return { pick: null, error: 'Нужна плоская грань (клик по грани, а не по ребру или скруглению).' }
    }
  }
  const localPoint = wrapper.worldToLocal(hit.point.clone())
  const tri = buildWorldFaceTriangleFromHit(hit)
  const pick: AssemblyPlaneSelection = {
    modelId,
    point: hit.point.clone(),
    localPoint,
    normal: analysis.normalLocal.clone(),
    surfaceKind: analysis.kind,
  }
  if (analysis.cylinderAxisLocal) pick.cylinderAxisLocal = analysis.cylinderAxisLocal.clone()
  if (tri) pick.previewGeometry = tri
  return { pick }
}

function buildWorldFaceTriangleFromHit(hit: THREE.Intersection): THREE.BufferGeometry | null {
  const mesh = hit.object as THREE.Mesh
  const face = hit.face
  const pos = mesh.geometry?.attributes?.position as THREE.BufferAttribute | undefined
  if (!face || !pos) return null
  const vA = new THREE.Vector3(pos.getX(face.a), pos.getY(face.a), pos.getZ(face.a)).applyMatrix4(mesh.matrixWorld)
  const vB = new THREE.Vector3(pos.getX(face.b), pos.getY(face.b), pos.getZ(face.b)).applyMatrix4(mesh.matrixWorld)
  const vC = new THREE.Vector3(pos.getX(face.c), pos.getY(face.c), pos.getZ(face.c)).applyMatrix4(mesh.matrixWorld)
  const g = new THREE.BufferGeometry().setAttribute(
    'position',
    new THREE.Float32BufferAttribute([vA.x, vA.y, vA.z, vB.x, vB.y, vB.z, vC.x, vC.y, vC.z], 3),
  )
  g.computeVertexNormals()
  return g
}

function assemblyIndicatorSizeForModel(modelId: string): number {
  const box = getAssemblyModelBox(modelId)
  if (!box) return 24
  const s = box.getSize(new THREE.Vector3())
  return Math.max(8, Math.min(100, Math.max(s.x, s.y, s.z) * 0.07))
}

/** Маркер плоскости по сохранённой точке и нормали (после перемещения модели остаётся корректным). */
function addAssemblyPlaneDiskIndicator(modelId: string, localPoint: THREE.Vector3, normalWorld: THREE.Vector3, color: number, opacity: number) {
  const g = modelGroupsById.get(modelId)
  if (!g || !assemblyHighlightGroup) return
  const nw = normalWorld.clone().normalize()
  const wp = g.localToWorld(localPoint.clone())
  const size = assemblyIndicatorSizeForModel(modelId)
  const geom = new THREE.PlaneGeometry(size, size)
  const mat = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity,
    side: THREE.DoubleSide,
    depthWrite: false,
  })
  const mesh = new THREE.Mesh(geom, mat)
  mesh.position.copy(wp)
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), nw)
  assemblyHighlightGroup.add(mesh)
}

function addStoredPlaneIndicator(sp: StoredAssemblyPlane, color: number, opacity = 0.5) {
  const grp = modelGroupsById.get(sp.modelId)
  if (!grp) return
  const local = new THREE.Vector3(sp.localPoint.x, sp.localPoint.y, sp.localPoint.z)
  const nLocal = new THREE.Vector3(sp.normal.x, sp.normal.y, sp.normal.z)
  const nw = nLocal.clone().transformDirection(grp.matrixWorld).normalize()
  addAssemblyPlaneDiskIndicator(sp.modelId, local, nw, color, opacity)
}

function worldCoordSystemScale(): number {
  const sceneBox = getFullSceneBox()
  if (sceneBox) {
    const s = sceneBox.getSize(new THREE.Vector3())
    return Math.max(800, Math.max(s.x, s.y, s.z) * 0.35)
  }
  return Math.max(800, loadedSceneCharDim * 0.35)
}

function syncWorldCoordSystemGroup() {
  if (!scene) return
  if (!showWorldCoordSystem.value) {
    if (worldCoordSystemGroup) worldCoordSystemGroup.visible = false
    return
  }
  if (!worldCoordSystemGroup) {
    worldCoordSystemGroup = new THREE.Group()
    worldCoordSystemGroup.name = 'WorldCoordSystem'
    const axes = new THREE.AxesHelper(1)
    axes.name = 'WorldAxes'
    worldCoordSystemGroup.add(axes)
    for (const opt of WORLD_COORD_PLANE_OPTIONS) {
      const { normal } = worldCoordPlaneDefinition(opt.id)
      const size = 1
      const geom = new THREE.PlaneGeometry(size, size)
      const mat = new THREE.MeshBasicMaterial({
        color: 0x88aacc,
        transparent: true,
        opacity: 0.06,
        side: THREE.DoubleSide,
        depthWrite: false,
      })
      const mesh = new THREE.Mesh(geom, mat)
      mesh.userData = { worldCoordPlaneId: opt.id, isWorldCoordPlane: true }
      mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal.clone().normalize())
      mesh.name = `WorldPlane_${opt.id}`
      worldCoordSystemGroup.add(mesh)
    }
    scene.add(worldCoordSystemGroup)
  }
  worldCoordSystemGroup.visible = true
  const scale = worldCoordSystemScale()
  worldCoordSystemGroup.position.set(0, 0, 0)
  worldCoordSystemGroup.scale.setScalar(scale)
  const axes = worldCoordSystemGroup.getObjectByName('WorldAxes') as THREE.AxesHelper | undefined
  if (axes) axes.scale.setScalar(1)
}

function selectWorldCoordPlane(id: WorldCoordPlaneId) {
  assemblyCoordWorldPlane.value = id
  refreshAllAssemblyVisuals()
  assemblyStatus.value = `Координатная плоскость: ${worldCoordPlaneOptionLabel(id)} (начало координат сцены 0,0,0).`
}

function addWorldCoordPlaneVisual(id: WorldCoordPlaneId, color: number, opacity: number) {
  if (!assemblyHighlightGroup) return
  const { normal } = worldCoordPlaneDefinition(id)
  const size = Math.max(loadedSceneCharDim * 1.25, 3000)
  const geom = new THREE.PlaneGeometry(size, size)
  const mat = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity,
    side: THREE.DoubleSide,
    depthWrite: false,
  })
  const mesh = new THREE.Mesh(geom, mat)
  mesh.position.copy(WORLD_COORD_PLANE_ORIGIN)
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal.clone().normalize())
  assemblyHighlightGroup.add(mesh)
}

function addPickPlaneVisual(p: AssemblyPlaneSelection, color: number, opacity: number) {
  if (p.previewGeometry && assemblyHighlightGroup) {
    const mat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity,
      side: THREE.DoubleSide,
      depthWrite: false,
    })
    assemblyHighlightGroup.add(new THREE.Mesh(p.previewGeometry.clone(), mat))
    return
  }
  const grp = modelGroupsById.get(p.modelId)
  if (!grp) return
  addAssemblyPlaneDiskIndicator(p.modelId, p.localPoint.clone(), p.normal.clone(), color, opacity * 0.85)
}

function refreshAllAssemblyVisuals() {
  if (!assemblyHighlightGroup) return
  disposeAssemblyHighlightGroupMeshes()
  const selId = selectedAssemblyMateId.value
  if (selId) {
    const m = assemblyMates.value.find((x) => x.id === selId)
    if (m) {
      if (m.type === 'symmetric') {
        addStoredPlaneIndicator(m.base1, 0x55cc77, 0.55)
        addStoredPlaneIndicator(m.base2, 0x228844, 0.55)
        addStoredPlaneIndicator(m.part1, 0xaa77ff, 0.55)
        addStoredPlaneIndicator(m.part2, 0x6633cc, 0.55)
      } else if (m.type === 'coord') {
        addStoredPlaneIndicator(m.sourcePlane, 0x3399ff, 0.55)
        addWorldCoordPlaneVisual(m.worldPlane, 0x44dd88, 0.32)
      } else {
        addStoredPlaneIndicator(m.sourcePlane, 0x3399ff, 0.55)
        addStoredPlaneIndicator(m.targetPlane, 0xff8833, 0.55)
      }
      return
    }
  }
  if (assemblyMateType.value === 'coord') {
    if (assemblySourcePlane.value) addPickPlaneVisual(assemblySourcePlane.value, 0x44aaff, 0.45)
    addWorldCoordPlaneVisual(assemblyCoordWorldPlane.value, 0x55ee99, 0.28)
  } else if (assemblyMateType.value === 'symmetric') {
    if (assemblySymBase1.value) addPickPlaneVisual(assemblySymBase1.value, 0x55dd88, 0.45)
    if (assemblySymBase2.value) addPickPlaneVisual(assemblySymBase2.value, 0x33aa55, 0.45)
    if (assemblySymPart1.value) addPickPlaneVisual(assemblySymPart1.value, 0xbb88ff, 0.45)
    if (assemblySymPart2.value) addPickPlaneVisual(assemblySymPart2.value, 0x8866dd, 0.45)
  } else {
    if (assemblySourcePlane.value) addPickPlaneVisual(assemblySourcePlane.value, 0x44aaff, 0.45)
    if (assemblyTargetPlane.value) addPickPlaneVisual(assemblyTargetPlane.value, 0xffaa44, 0.45)
  }
}

function selectAssemblyMateRow(id: string | null) {
  selectedAssemblyMateId.value = selectedAssemblyMateId.value === id ? null : id
  refreshAllAssemblyVisuals()
}

function clearAssemblyPickStateAfterMateApply() {
  disposePlanePreviewGeometry(assemblySourcePlane.value ?? undefined)
  disposePlanePreviewGeometry(assemblyTargetPlane.value ?? undefined)
  disposePlanePreviewGeometry(assemblySymBase1.value ?? undefined)
  disposePlanePreviewGeometry(assemblySymBase2.value ?? undefined)
  disposePlanePreviewGeometry(assemblySymPart1.value ?? undefined)
  disposePlanePreviewGeometry(assemblySymPart2.value ?? undefined)
  assemblySourcePlane.value = null
  assemblyTargetPlane.value = null
  assemblySymBase1.value = null
  assemblySymBase2.value = null
  assemblySymPart1.value = null
  assemblySymPart2.value = null
  selectedAssemblyMateId.value = null
  refreshAllAssemblyVisuals()
}

/** Esc: сбросить только выбранные для следующего сопряжения плоскости (связи в списке не удаляются). */
function clearPendingAssemblyPlaneSelections() {
  disposePlanePreviewGeometry(assemblySourcePlane.value ?? undefined)
  disposePlanePreviewGeometry(assemblyTargetPlane.value ?? undefined)
  disposePlanePreviewGeometry(assemblySymBase1.value ?? undefined)
  disposePlanePreviewGeometry(assemblySymBase2.value ?? undefined)
  disposePlanePreviewGeometry(assemblySymPart1.value ?? undefined)
  disposePlanePreviewGeometry(assemblySymPart2.value ?? undefined)
  assemblySourcePlane.value = null
  assemblyTargetPlane.value = null
  assemblySymBase1.value = null
  assemblySymBase2.value = null
  assemblySymPart1.value = null
  assemblySymPart2.value = null
  assemblyPickTarget.value = null
  assemblyStatus.value = ''
  refreshAllAssemblyVisuals()
}

watch(
  assemblyMateType,
  () => {
    stripStaleAssemblyFaceTriangles()
    assemblySymBase1.value = null
    assemblySymBase2.value = null
    assemblySymPart1.value = null
    assemblySymPart2.value = null
    assemblySourcePlane.value = null
    assemblyTargetPlane.value = null
    selectedAssemblyMateId.value = null
    refreshAllAssemblyVisuals()
  },
  { flush: 'post' },
)

watch([dimArrowSizeMm, dimLineOffsetMm, dimFontSizeMm], () => {
  rebuildSavedMeasurementsVisuals()
})

watch(
  () => props.measureMode,
  (enabled) => {
    if (enabled === undefined) return
    if (enabled === measureModeRef.value) return
    measureModeRef.value = enabled
    if (!enabled) clearMeasurements()
  },
  { immediate: true },
)

watch(
  () => props.measureType,
  (t) => {
    if (!t || t === measureTypeRef.value) return
    setMeasureType(t)
  },
)

watch(
  () => props.measureSnapMode,
  (mode) => {
    if (mode) measureSnapMode = mode
  },
  { immediate: true },
)

watch(selectedMeasurementId, () => {
  refreshMeasurementReferenceFaceHighlights()
})

function onCanvasMouseDown(ev: MouseEvent) {
  if (partContextMenuOpen.value) partContextMenuOpen.value = false
  if (ev.button === 0 && placementActive.value && placementModelId.value && camera && renderer) {
    const pt = pickPlacementPlanePoint(ev.clientX, ev.clientY)
    const g = modelGroupsById.get(placementModelId.value)
    if (pt && g) placeModelAnchorAtWorld(g, pt)
    confirmModelPlacement()
    ev.preventDefault()
    ev.stopPropagation()
    return
  }
  if (ev.button === 0 && isPartBoxSelectEnabled()) {
    beginBoxSelectDrag(ev)
    return
  }
  if (!camera || !controls || !meshGroup) return
  if (tryBeginMeasurementOffsetDrag(ev)) return
  if (ev.button === 0 && modelRotateMode.value) {
    const rect = renderer.domElement.getBoundingClientRect()
    const mx = ((ev.clientX - rect.left) / rect.width) * 2 - 1
    const my = -((ev.clientY - rect.top) / rect.height) * 2 + 1
    raycaster.setFromCamera(new THREE.Vector2(mx, my), camera)
    const rotateHit = pickSolidSurfaceHit(intersectPickableMeshes(raycaster))
    if (rotateHit) {
      const wrapper = findWrapperGroup(rotateHit.object)
      if (wrapper) {
        const mid = String(wrapper.userData?.modelId ?? '')
        if (mid && !isModelPinned(mid)) {
          meshGroup.updateMatrixWorld(true)
          const box = new THREE.Box3().setFromObject(wrapper)
          const cw = box.getCenter(new THREE.Vector3())
          dragRotatePivotLocal = wrapper.parent!.worldToLocal(cw.clone())
          dragRotateUndoBefore = getTransformSnapshot(wrapper)
          draggedRotateWrapper = wrapper
          dragRotateLastClientX = ev.clientX
          dragRotateLastClientY = ev.clientY
          didDragModel = false
          controls.enabled = false
          ev.preventDefault()
          ev.stopPropagation()
        }
      }
    }
    return
  }
  if (ev.button === 0 && leftButtonMoveModel.value && !modelRotateMode.value) {
    const rect = renderer.domElement.getBoundingClientRect()
    const mx = ((ev.clientX - rect.left) / rect.width) * 2 - 1
    const my = -((ev.clientY - rect.top) / rect.height) * 2 + 1
    raycaster.setFromCamera(new THREE.Vector2(mx, my), camera)
    const moveHit = pickSolidSurfaceHit(intersectPickableMeshes(raycaster))
    if (moveHit) {
      const wrapper = findWrapperGroup(moveHit.object)
      if (wrapper) {
        const mid = String(wrapper.userData?.modelId ?? '')
        if (mid && isModelPinned(mid)) return
        dragMoveUndoBefore = getTransformSnapshot(wrapper)
        draggedModelGroup = wrapper
        dragStartModelPos = wrapper.position.clone()
        dragStartIntersection = moveHit.point.clone()
        didDragModel = false
        controls.enabled = false
        ev.preventDefault()
        ev.stopPropagation()
      }
    }
  }
}

function onCanvasPointerDownCapture(ev: PointerEvent) {
  if (ev.button !== 2) return
  rightMouseDown = true
  rightMouseDragged = false
  orbitPivotAppliedThisGesture = false
  rightMouseDownX = ev.clientX
  rightMouseDownY = ev.clientY
  pendingOrbitPivot = null
  contextMenuCanShow.value = tryPickContextTarget(ev.clientX, ev.clientY)
  if (camera && controls && meshGroup?.children.length && controls.enabled) {
    pendingOrbitPivot = pickOrbitPivotFromClient(ev.clientX, ev.clientY)
    controls.noRotate = true
  }
}

function onCanvasContextMenu(ev: MouseEvent) {
  // Меню открываем только на mouseup без перетаскивания; нативное отключаем всегда.
  const rect = renderer.domElement.getBoundingClientRect()
  ev.preventDefault()
  ev.stopPropagation()
  partContextMenuX.value = ev.clientX - rect.left
  partContextMenuY.value = ev.clientY - rect.top
}

function tryPickContextTarget(clientX: number, clientY: number): boolean {
  if (!camera || !renderer || !meshGroup) return false
  const rect = renderer.domElement.getBoundingClientRect()
  const mx = ((clientX - rect.left) / rect.width) * 2 - 1
  const my = -((clientY - rect.top) / rect.height) * 2 + 1
  raycaster.setFromCamera(new THREE.Vector2(mx, my), camera)
  const pickHit = pickSolidSurfaceHit(intersectPickableMeshes(raycaster))
  if (pickHit) {
    const wrapper = findWrapperGroup(pickHit.object)
    const partNode = wrapper ? findPartNodeInWrapper(pickHit.object, wrapper) : null
    if (wrapper && partNode) {
      contextMenuTargetPart = partNode
      const mid = String(wrapper.userData?.modelId ?? '')
      contextMenuTargetModelId.value = mid
      if (mid) focusedModelId.value = mid
      const mesh = partNode instanceof THREE.Mesh ? partNode : null
      const row = mesh ? findPartRowForMeshUuid(mid, mesh.uuid) : null
      contextMenuTargetIsHidden.value = row ? !row.visible : !partNode.visible
      return true
    }
  }
  const hiddenHits = raycaster.intersectObject(hiddenOutlineGroup, true)
  if (hiddenHits.length > 0) {
    const hitObj = hiddenHits[0].object as THREE.Object3D
    const modelId = String(hitObj.userData?.modelId ?? '')
    const objectId = String(hitObj.userData?.objectId ?? '')
    const group = modelGroupsById.get(modelId)
    if (!group || !objectId) return false
    let target: THREE.Object3D | null = null
    group.traverse((obj: THREE.Object3D) => {
      if (!target && obj.uuid === objectId) target = obj
    })
    if (!target) return false
    contextMenuTargetPart = target
    contextMenuTargetModelId.value = modelId
    if (modelId) focusedModelId.value = modelId
    const mesh = target instanceof THREE.Mesh ? target : null
    const row = mesh ? findPartRowForMeshUuid(modelId, mesh.uuid) : null
    contextMenuTargetIsHidden.value = row ? !row.visible : !target.visible
    return true
  }
  return false
}

function showContextMenuAt(clientX: number, clientY: number) {
  if (!renderer) return
  const rect = renderer.domElement.getBoundingClientRect()
  partContextMenuX.value = clientX - rect.left
  partContextMenuY.value = clientY - rect.top
  partContextMenuOpen.value = true
}

function showSelectedPartFromContextMenu() {
  const mid = contextMenuTargetModelId.value
  if (!contextMenuTargetPart || !mid) return
  setComponentVisibilityForObject(mid, contextMenuTargetPart, true)
  partContextMenuOpen.value = false
  contextMenuTargetIsHidden.value = false
  contextMenuTargetPart = null
  contextMenuTargetModelId.value = null
}

function hideSelectedPartFromContextMenu() {
  const mid = contextMenuTargetModelId.value
  if (!contextMenuTargetPart || !mid) return
  setComponentVisibilityForObject(mid, contextMenuTargetPart, false)
  partContextMenuOpen.value = false
  contextMenuTargetIsHidden.value = false
  contextMenuTargetPart = null
  contextMenuTargetModelId.value = null
}

function togglePinFromContextMenu() {
  const mid = contextMenuTargetModelId.value
  if (!mid) return
  togglePinModelId(mid)
  partContextMenuOpen.value = false
}

function onGlobalMouseDown(ev: MouseEvent) {
  if (!partContextMenuOpen.value) return
  const target = ev.target as HTMLElement | null
  if (target?.closest('.viewer-part-context-menu')) return
  partContextMenuOpen.value = false
  contextMenuTargetIsHidden.value = false
}

function onCanvasMouseMovePan(ev: MouseEvent) {
  if (boxSelectDrag) {
    updateBoxSelectRectFromClient(ev.clientX, ev.clientY)
    return
  }
  if (rightMouseDown) tryApplyPendingOrbitPivotOnDrag(ev)
  if (offsetDragPending && !draggedMeasurementOffset) {
    const dx = ev.clientX - offsetDragPending.startX
    const dy = ev.clientY - offsetDragPending.startY
    if (Math.hypot(dx, dy) >= DIM_DRAG_MIN_PX) {
      draggedMeasurementOffset = offsetDragPending
      offsetDragPending = null
      draggedModelGroup = null
      dragStartModelPos = null
      dragStartIntersection = null
      if (controls) controls.enabled = false
    }
  }
  if (draggedMeasurementOffset) {
    ev.preventDefault()
    ev.stopPropagation()
    const dx = ev.clientX - draggedMeasurementOffset.startX
    const dy = ev.clientY - draggedMeasurementOffset.startY
    const projectedDeltaPx = dx * draggedMeasurementOffset.axisX + dy * draggedMeasurementOffset.axisY
    const nextOffset = draggedMeasurementOffset.startOffset + projectedDeltaPx * 1.4
    commitMeasurementLineOffset(draggedMeasurementOffset.id, nextOffset)
    rebuildSavedMeasurementsVisuals()
    updateSavedMeasurementLabelPositions()
    return
  }
  if (draggedRotateWrapper && camera && controls && dragRotatePivotLocal) {
    ev.preventDefault()
    ev.stopPropagation()
    didDragModel = true
    const dx = ev.clientX - dragRotateLastClientX
    const dy = ev.clientY - dragRotateLastClientY
    dragRotateLastClientX = ev.clientX
    dragRotateLastClientY = ev.clientY
    rotateWrapperAroundPivotScreenAxes(
      draggedRotateWrapper,
      dragRotatePivotLocal,
      dx,
      dy,
      camera,
      controls.target,
    )
    return
  }
  if (draggedMeasurementOffset || offsetDragPending) return
  if (!draggedModelGroup || !dragStartModelPos || !dragStartIntersection || !camera || !controls) return
  ev.preventDefault()
  ev.stopPropagation()
  didDragModel = true
  const rect = renderer.domElement.getBoundingClientRect()
  const mx = ((ev.clientX - rect.left) / rect.width) * 2 - 1
  const my = -((ev.clientY - rect.top) / rect.height) * 2 + 1
  const r = new THREE.Raycaster()
  r.setFromCamera(new THREE.Vector2(mx, my), camera)
  const dir = new THREE.Vector3().subVectors(camera.position, controls.target).normalize()
  dragPlane.setFromNormalAndCoplanarPoint(dir, dragStartIntersection)
  if (r.ray.intersectPlane(dragPlane, dragIntersect)) {
    const delta = dragIntersect.clone().sub(dragStartIntersection)
    draggedModelGroup.position.copy(dragStartModelPos).add(delta)
  }
}

function onCanvasMouseUp(ev: MouseEvent) {
  if (ev.button === 0 && boxSelectDrag) {
    finishBoxSelect(ev.clientX, ev.clientY)
    ev.preventDefault()
    ev.stopPropagation()
    return
  }
  if (ev.button === 2) {
    if (rightMouseDown && !rightMouseDragged && contextMenuCanShow.value && tryPickContextTarget(ev.clientX, ev.clientY)) {
      showContextMenuAt(ev.clientX, ev.clientY)
    }
    rightMouseDown = false
    rightMouseDragged = false
    pendingOrbitPivot = null
    orbitPivotAppliedThisGesture = false
    if (controls) controls.noRotate = false
    contextMenuCanShow.value = false
  }
  if (ev.button === 0 && offsetDragPending) {
    offsetDragPending = null
  }
  if (ev.button === 0 && draggedMeasurementOffset) {
    const drag = draggedMeasurementOffset
    const dx = ev.clientX - drag.startX
    const dy = ev.clientY - drag.startY
    const wasDrag = Math.hypot(dx, dy) >= DIM_DRAG_MIN_PX
    const row = wasDrag ? measurementHistory.value.find((m) => m.id === drag.id) : null
    draggedMeasurementOffset = null
    draggedModelGroup = null
    dragStartModelPos = null
    dragStartIntersection = null
    if (controls) controls.enabled = true
    if (wasDrag && row) {
      commitMeasurementLineOffset(drag.id, row.lineOffsetMm ?? drag.startOffset)
      didDragMeasurement = true
      ev.preventDefault()
      ev.stopPropagation()
      return
    }
  }
  if (ev.button === 0 && draggedRotateWrapper) {
    const w = draggedRotateWrapper
    const rid = String(w.userData?.modelId ?? '')
    const after = getTransformSnapshot(w)
    if (dragRotateUndoBefore && !transformsEqual(dragRotateUndoBefore, after)) {
      pushTransformUndo({ modelId: rid, before: dragRotateUndoBefore, after })
    }
    dragRotateUndoBefore = null
    draggedRotateWrapper = null
    dragRotatePivotLocal = null
    if (controls) controls.enabled = true
    ev.preventDefault()
    ev.stopPropagation()
    if (rid && assemblyMates.value.length) {
      reapplyAllAssemblyMates()
    } else if (rid) {
      meshGroup.updateMatrixWorld(true)
      refreshSelectedMeasurementAfterTransform()
      rebuildSavedMeasurementsVisuals()
    }
    return
  }
  if (ev.button === 0 && draggedModelGroup) {
    const w = draggedModelGroup
    const movedId = String(w.userData?.modelId ?? '')
    const after = getTransformSnapshot(w)
    if (dragMoveUndoBefore && !transformsEqual(dragMoveUndoBefore, after)) {
      pushTransformUndo({ modelId: movedId, before: dragMoveUndoBefore, after })
    }
    dragMoveUndoBefore = null
    draggedModelGroup = null
    dragStartModelPos = null
    dragStartIntersection = null
    if (controls) controls.enabled = true
    ev.preventDefault()
    ev.stopPropagation()
    if (movedId && assemblyMates.value.length) {
      reapplyAllAssemblyMates()
    } else if (movedId) {
      meshGroup.updateMatrixWorld(true)
      refreshSelectedMeasurementAfterTransform()
      rebuildSavedMeasurementsVisuals()
    }
  }
}

function onCanvasWheel(ev: WheelEvent) {
  if (!camera || !controls || !containerRef.value) return
  ev.preventDefault()
  normalizeMouseSettings()
  const now = performance.now()
  const rect = renderer.domElement.getBoundingClientRect()
  const mx = ((ev.clientX - rect.left) / rect.width) * 2 - 1
  const my = -((ev.clientY - rect.top) / rect.height) * 2 + 1
  if (zoomAnchorPoint === null || now - lastWheelTime > mouseZoomGestureMs.value) {
    const raycaster = new THREE.Raycaster()
    raycaster.setFromCamera(new THREE.Vector2(mx, my), camera)
    zoomToCursorPlane.setFromNormalAndCoplanarPoint(
      zoomToCursorDir.copy(camera.position).sub(controls.target).normalize(),
      controls.target
    )
    if (raycaster.ray.intersectPlane(zoomToCursorPlane, zoomToCursorPoint) === null) return
    zoomAnchorPoint = zoomToCursorPoint.clone()
  }
  lastWheelTime = now
  const dist = camera.position.distanceTo(zoomAnchorPoint)
  const sign = mouseInvertWheel.value ? (ev.deltaY > 0 ? 1 : -1) : (ev.deltaY > 0 ? -1 : 1)
  /** Процентный зум (~5–7% за шаг): не зависит от расстояния — без рывков на больших сборках. */
  const step = mouseZoomSpeed.value * 2.4
  const zoomFactor = sign > 0 ? 1 / (1 + step) : 1 + step
  let newDist = dist * zoomFactor
  const minD = mouseMinDistance.value
  const maxD = mouseMaxDistance.value
  newDist = Math.max(minD, Math.min(maxD, newDist))
  const dirFromPoint = camera.position.clone().sub(zoomAnchorPoint).normalize()
  camera.position.copy(zoomAnchorPoint).add(dirFromPoint.multiplyScalar(newDist))
  controls.target.copy(zoomAnchorPoint)
  updateCameraClipPlanes()
  rebuildSavedMeasurementsVisuals()
}

function onCanvasClick(ev: MouseEvent) {
  if (partContextMenuOpen.value) partContextMenuOpen.value = false
  if (didDragModel) {
    didDragModel = false
    return
  }
  if (didDragMeasurement) {
    didDragMeasurement = false
    return
  }
  if (didBoxSelect) {
    didBoxSelect = false
    return
  }
  if (!renderer || !camera || !meshGroup.children.length) {
    if (measureModeRef.value) logger.info('Viewer3D', 'Клик: модель не загружена или нет сцены, измерение игнорируется')
    return
  }
  const rect = renderer.domElement.getBoundingClientRect()
  mouse.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1
  mouse.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1
  raycaster.setFromCamera(mouse, camera)
  meshGroup.updateMatrixWorld(true)
  const hits = intersectPickableMeshes(raycaster)
  if (remarkAnchorPickMode.value && selectedRemark.value) {
    const surfaceHit = pickSolidSurfaceHit(hits)
    if (!surfaceHit) {
      window.alert('Кликните по детали в сцене, чтобы поставить якорь.')
      return
    }
    pickRemarkAnchorFromHit(surfaceHit)
    return
  }
  if (assemblyPickTarget.value) {
    const surfaceHit = pickSolidSurfaceHit(hits)
    if (!surfaceHit) {
      assemblyStatus.value = 'Не попали в модель. Кликните по нужной плоскости.'
      return
    }
    pickAssemblyPlaneFromHit(surfaceHit)
    return
  }
  if (measureModeRef.value && !shouldDeferSavedMeasurementPick()) {
    const pickedDim = pickLinearMeasurementAtClient(ev.clientX, ev.clientY)
    if (pickedDim) {
      const placingNewDistancePoint =
        measureTypeRef.value === 'distance'
        && measurementPoints.length === 0
        && !!pickSolidSurfaceHit(hits)
      if (!placingNewDistancePoint) {
        selectedMeasurementId.value = pickedDim.id
        rebuildSavedMeasurementsVisuals()
        return
      }
    }
  }
  if (measureModeRef.value && measureTypeRef.value === 'cad-linear') {
    const faceHit = firstMeshFaceHit(hits)
    if (!faceHit) {
      cadLinearStatus.value = 'Линейный размер: кликните по плоской грани модели.'
      return
    }
    pickCadLinearPlaneFromHit(faceHit)
    return
  }
  if (
    !measureModeRef.value &&
    (assemblyPanelOpen.value || (assemblySourceModelId.value && assemblyTargetModelId.value)) &&
    hits.length > 0
  ) {
    const surfaceHit = pickSolidSurfaceHit(hits)
    if (surfaceHit) {
      const wrapper = findWrapperGroup(surfaceHit.object)
      const modelId = String(wrapper?.userData?.modelId ?? '')
      const autoTarget = modelId ? inferAutoAssemblyPickTarget(modelId) : null
      if (autoTarget) {
        assemblyPickTarget.value = autoTarget
        pickAssemblyPlaneFromHit(surfaceHit)
        return
      }
    }
  }
  if (sectionModeRef.value) {
    const surfaceHit = pickSolidSurfaceHit(hits)
    if (!surfaceHit) return
    const worldNormal = surfaceHit.face!.normal.clone().transformDirection(surfaceHit.object.matrixWorld)
    setSectionFromHit(surfaceHit.point.clone(), worldNormal)
    return
  }
  if (!measureModeRef.value) {
    const partHit = firstSolidPartHit(hits)
    if (partHit) {
      const wrap = findWrapperGroup(partHit.mesh)
      if (wrap) {
        const mid = String(wrap.userData?.modelId ?? '')
        if (mid) {
          focusedModelId.value = mid
          const row = findPartRowForMeshUuid(mid, partHit.mesh.uuid)
          if (row) selectComponentRow(mid, row.id, ev)
        }
      }
      if (partHit.hit.face) {
        selectedFacePoint = partHit.hit.point.clone()
        selectedFaceNormal = partHit.hit.face.normal
          .clone()
          .transformDirection(partHit.mesh.matrixWorld)
          .normalize()
      }
    } else {
      focusedModelId.value = null
    }
    return
  }
  const clickId = ++measureClickSeq
  const clickT0 = performance.now()
  logger.info(
    'Viewer3D',
    `MeasureClick#${clickId} start: type=${measureTypeRef.value}, hits=${hits.length}, points=${measurementPoints.length}, mode=${measureModeRef.value ? 'on' : 'off'}`
  )
  if (measureTypeRef.value === 'radius') {
    const hit = pickSolidSurfaceHit(hits)
    if (!hit) {
      logger.info('Viewer3D', `MeasureClick#${clickId} radius: no hits`)
      return
    }
    const mesh = hit.object as THREE.Mesh
    const wrapper = findWrapperGroup(hit.object)
    const modelId = String(wrapper?.userData?.modelId ?? '')
    const faceIndex = typeof (hit as THREE.Intersection & { faceIndex?: number }).faceIndex === 'number'
      ? (hit as THREE.Intersection & { faceIndex: number }).faceIndex
      : Math.floor(hit.face!.a / 3)
    const verts = getVerticesAroundFace(mesh, faceIndex)
    const normal = hit.face!.normal.clone().transformDirection(mesh.matrixWorld).normalize()
    let fit = fitCircleToPoints(verts, normal)
    if (!fit) {
      const radiusInfo = getHoverRadiusInfo(mesh, faceIndex, normal)
      if (radiusInfo) fit = { center: radiusInfo.center, radius: radiusInfo.radius }
    }
    if (fit) {
      radiusOrDiameterResult = { center: fit.center, radius: fit.radius, normal, isDiameter: false }
      const localCenter = meshPointToSaved(mesh, fit.center)
      const localNormal = meshNormalToSaved(mesh, normal)
      saveRadiusMeasurement(fit.center, fit.radius, normal, modelId || null, localCenter, localNormal, mesh.uuid)
      logger.info(
        'Viewer3D',
        `MeasureClick#${clickId} radius fit: center=${formatVec3(fit.center)}, r=${fit.radius.toFixed(2)}`
      )
      updateMeasurementGraphics()
      logger.info('Viewer3D', `MeasureClick#${clickId} done radius: ${(performance.now() - clickT0).toFixed(1)} ms`)
    } else {
      logger.warn('Viewer3D', `MeasureClick#${clickId} radius: fit failed`)
    }
    return
  }
  if (measureTypeRef.value === 'diameter') {
    const hit = pickSolidSurfaceHit(hits)
    if (!hit) {
      logger.info('Viewer3D', `MeasureClick#${clickId} diameter: no hits`)
      return
    }
    if (firstClickHole && measurementPoints.length === 2) {
      firstClickHole = null
      secondHoleResult = null
      measurementPoints = []
      measurementPointNormals = []
      measurementPointMeshUuids = []
      radiusOrDiameterResult = null
      updateMeasurementGraphics()
    }
    const mesh = hit.object as THREE.Mesh
    const wrapper = findWrapperGroup(hit.object)
    const modelId = String(wrapper?.userData?.modelId ?? '')
    const faceIndex = typeof (hit as THREE.Intersection & { faceIndex?: number }).faceIndex === 'number'
      ? (hit as THREE.Intersection & { faceIndex: number }).faceIndex
      : Math.floor(hit.face!.a / 3)
    const worldNormalHit = hit.face!.normal.clone().transformDirection(mesh.matrixWorld).normalize()
    let hole = getHoleFromHit(mesh, hit.point)
    let radiusInfo: { center: THREE.Vector3; radius: number } | null = null
    if (!hole) {
      radiusInfo = getHoverRadiusInfo(mesh, faceIndex, worldNormalHit)
      if (radiusInfo && isCylinderAHole(mesh, radiusInfo.center, radiusInfo.radius, worldNormalHit, raycaster)) {
        hole = { center: radiusInfo.center.clone(), radius: radiusInfo.radius, normal: worldNormalHit.clone() }
      }
    }
    if (firstClickHole === null) {
      if (!hole && radiusInfo) {
        hole = { center: radiusInfo.center.clone(), radius: radiusInfo.radius, normal: worldNormalHit.clone() }
      }
      if (!hole) return
      firstClickHole = { center: hole.center.clone(), radius: hole.radius, normal: hole.normal.clone() }
      firstClickHoleModelId = modelId || null
      firstClickHoleMeshUuid = mesh.uuid
      firstClickHoleLocalCenter = meshPointToSaved(mesh, hole.center)
      firstClickHoleLocalNormal = meshNormalToSaved(mesh, hole.normal)
      radiusOrDiameterResult = { center: hole.center, radius: hole.radius, normal: hole.normal, isDiameter: true }
      updateMeasurementGraphics()
      logger.info(
        'Viewer3D',
        `MeasureClick#${clickId} diameter first hole: center=${formatVec3(hole.center)}, r=${hole.radius.toFixed(2)}`
      )
      return
    }
    if (hole) {
      secondHoleResult = { center: hole.center.clone(), radius: hole.radius, normal: hole.normal.clone() }
      measurementPoints = [firstClickHole.center.clone(), secondHoleResult.center.clone()]
      measurementPointNormals = [null, null]
      measurementPointModelIds = [firstClickHoleModelId, modelId || null]
      measurementPointMeshUuids = [firstClickHoleMeshUuid, mesh.uuid]
      measurementPointLocals = [
        firstClickHoleLocalCenter,
        meshPointToSaved(mesh, hole.center),
      ]
      measurementPointNormalLocals = [firstClickHoleLocalNormal, meshNormalToSaved(mesh, hole.normal)]
      saveDiameterMeasurement(
        firstClickHole.center,
        firstClickHole.radius,
        firstClickHole.normal,
        firstClickHoleModelId,
        firstClickHoleLocalCenter,
        firstClickHoleLocalNormal,
        hole.center.clone(),
        modelId || null,
        meshPointToSaved(mesh, hole.center),
        firstClickHoleMeshUuid,
        mesh.uuid,
      )
    } else {
      const candidates = getSnapCandidates(hit)
      const closest = getClosestSnapPoint(candidates, camera, mouse)
      const point = (closest ?? getPointFromHit(hit)).clone()
      const worldNormal = hit.face!.normal.clone().transformDirection(mesh.matrixWorld).normalize()
      measurementPoints = [firstClickHole.center.clone(), point]
      measurementPointNormals = [firstClickHole.normal.clone(), worldNormal]
      measurementPointModelIds = [firstClickHoleModelId, modelId || null]
      measurementPointMeshUuids = [firstClickHoleMeshUuid, mesh.uuid]
      measurementPointLocals = [
        firstClickHoleLocalCenter,
        meshPointToSaved(mesh, point),
      ]
      measurementPointNormalLocals = [
        firstClickHoleLocalNormal,
        meshNormalToSaved(mesh, worldNormal),
      ]
      saveDiameterMeasurement(
        firstClickHole.center,
        firstClickHole.radius,
        firstClickHole.normal,
        firstClickHoleModelId,
        firstClickHoleLocalCenter,
        firstClickHoleLocalNormal,
        undefined,
        undefined,
        undefined,
        firstClickHoleMeshUuid,
        mesh.uuid,
      )
    }
    updateMeasurementGraphics()
    logger.info(
      'Viewer3D',
      `MeasureClick#${clickId} done diameter: points=${measurementPoints.length}, ${(performance.now() - clickT0).toFixed(1)} ms`
    )
    return
  }
  if (measureTypeRef.value === 'arc') {
    const hit = pickSolidSurfaceHit(hits)
    if (!hit) {
      logger.info('Viewer3D', `MeasureClick#${clickId} arc: no hits`)
      return
    }
    const mesh = hit.object as THREE.Mesh
    const candidates = getSnapCandidates(hit)
    const closest = getClosestSnapPoint(candidates, camera, mouse)
    const point = (closest ?? getPointFromHit(hit)).clone()
    if (arcFirstPoint === null) {
      arcFirstPoint = point
      arcMesh = mesh
      logger.info('Viewer3D', `MeasureClick#${clickId} arc: first point=${formatVec3(point)}`)
      return
    }
    const result = shortestPathOnMesh(arcMesh!, arcFirstPoint, point)
    const arcWrapper = findWrapperGroup(mesh)
    const arcModelId = String(arcWrapper?.userData?.modelId ?? '')
    arcFirstPoint = null
    arcMesh = null
    if (result) {
      arcResult = result
      const arcPathLocal = arcWrapper ? result.path.map((p) => vecToSaved(arcWrapper.worldToLocal(p.clone()))) : null
      saveArcMeasurement(result.path, result.length, arcModelId || null, arcPathLocal)
      updateMeasurementGraphics()
      logger.info(
        'Viewer3D',
        `MeasureClick#${clickId} done arc: pathPts=${result.path.length}, len=${result.length.toFixed(2)}, ${(performance.now() - clickT0).toFixed(1)} ms`
      )
    } else {
      logger.warn('Viewer3D', `MeasureClick#${clickId} arc: path not found`)
    }
    return
  }
  if (measureTypeRef.value === 'hole-center-distance') {
    const hit = pickSolidSurfaceHit(hits)
    if (!hit) {
      logger.info('Viewer3D', `MeasureClick#${clickId} hole-center-distance: no hits`)
      return
    }
    const mesh = hit.object as THREE.Mesh
    const wrapper = findWrapperGroup(mesh)
    const modelId = String(wrapper?.userData?.modelId ?? '')
    const faceIndex = typeof (hit as THREE.Intersection & { faceIndex?: number }).faceIndex === 'number'
      ? (hit as THREE.Intersection & { faceIndex: number }).faceIndex
      : Math.floor(hit.face!.a / 3)
    const worldNormalHit = hit.face!.normal.clone().transformDirection(mesh.matrixWorld).normalize()
    let center: THREE.Vector3
    const loops = getBoundaryLoops(mesh)
    if (loops.length > 0) {
      let bestLoop = loops[0]
      let bestDist = hit.point.distanceTo(loops[0].reduce((a, p) => a.add(p), new THREE.Vector3(0, 0, 0)).divideScalar(loops[0].length))
      for (const loop of loops) {
        const cen = loop.reduce((a, p) => a.add(p.clone()), new THREE.Vector3(0, 0, 0)).divideScalar(loop.length)
        const d = hit.point.distanceTo(cen)
        if (d < bestDist) {
          bestDist = d
          bestLoop = loop
        }
      }
      const n = bestLoop.length >= 3
        ? new THREE.Vector3().crossVectors(
            bestLoop[1].clone().sub(bestLoop[0]),
            bestLoop[2].clone().sub(bestLoop[0]),
          ).normalize()
        : new THREE.Vector3(0, 1, 0)
      const fit = fitCircleToPoints(bestLoop, n)
      if (!fit) {
        logger.warn('Viewer3D', `MeasureClick#${clickId} hole-center-distance: circle fit failed`)
        return
      }
      center = fit.center.clone()
    } else {
      const radiusInfo = getHoverRadiusInfo(mesh, faceIndex, worldNormalHit)
      if (!radiusInfo || !isCylinderAHole(mesh, radiusInfo.center, radiusInfo.radius, worldNormalHit, raycaster)) {
        logger.warn('Viewer3D', `MeasureClick#${clickId} hole-center-distance: no valid hole`)
        return
      }
      center = radiusInfo.center.clone()
    }
    if (holeCenterFirst === null) {
      holeCenterFirst = center
      holeCenterFirstModelId = modelId || null
      holeCenterFirstMeshUuid = mesh.uuid
      holeCenterFirstLocal = meshPointToSaved(mesh, center)
      logger.info('Viewer3D', `MeasureClick#${clickId} hole-center-distance first center=${formatVec3(center)}`)
      return
    }
    const a = holeCenterFirst.clone()
    const b = center.clone()
    const row: SavedMeasurement = {
      id: `m_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      type: 'distance',
      createdAt: new Date().toLocaleTimeString('ru-RU'),
      lengthMm: a.distanceTo(b),
      parallelMm: 0,
      trianglePerpMm: 0,
      surfacePerpMm: null,
      p1: vecToSaved(a),
      p2: vecToSaved(b),
      n1: null,
      n2: null,
      modelId1: holeCenterFirstModelId,
      modelId2: modelId || null,
      meshUuid1: holeCenterFirstMeshUuid,
      meshUuid2: mesh.uuid,
      p1Local: holeCenterFirstLocal,
      p2Local: meshPointToSaved(mesh, center),
      n1Local: null,
      n2Local: null,
    }
    holeCenterFirst = null
    holeCenterFirstModelId = null
    holeCenterFirstMeshUuid = null
    holeCenterFirstLocal = null
    measurementHistory.value = [row, ...measurementHistory.value].slice(0, 200)
    selectedMeasurementId.value = row.id
    rebuildSavedMeasurementsVisuals()
    measurementPoints = []
    measurementPointNormals = []
    updateMeasurementGraphics()
    logger.info('Viewer3D', `MeasureClick#${clickId} done hole-center-distance: ${(performance.now() - clickT0).toFixed(1)} ms`)
    return
  }
  const hit = pickSolidSurfaceHit(hits)
  if (!hit) {
    logger.info('Viewer3D', `MeasureClick#${clickId} distance: no hits`)
    return
  }
  const mesh = hit.object as THREE.Mesh
  const wrapper = findWrapperGroup(hit.object)
  const modelId = String(wrapper?.userData?.modelId ?? '')
  const face = hit.face!
  const worldNormal = face.normal.clone().transformDirection(mesh.matrixWorld).normalize()
  const candidates = getSnapCandidates(hit)
  const closest = getClosestSnapPoint(candidates, camera, mouse)
  const point = (closest ?? getPointFromHit(hit)).clone()
  const faceGeom = buildFaceHighlightGeometryFromHit(hit)

  if (measurementPoints.length >= 2) {
    selectedMeasurementId.value = null
    measurementPoints = [point]
    measurementPointNormals = [worldNormal]
    measurementPointModelIds = [modelId || null]
    measurementPointMeshUuids = [mesh.uuid]
    measurementPointLocals = [meshPointToSaved(mesh, point)]
    measurementPointNormalLocals = [meshNormalToSaved(mesh, worldNormal)]
    measurePreviewPoint = null
    measureStatusHint.value = 'Ведите мышь ко 2-й точке. Клик — зафиксировать. Esc — отмена.'
    for (const g of measurementFaceGeometries) g.dispose()
    measurementFaceGeometries = []
    if (faceGeom) measurementFaceGeometries.push(faceGeom)
  } else {
    if (measurementPoints.length === 0) selectedMeasurementId.value = null
    pushMeasureAnchor(mesh, modelId, point, worldNormal)
    measurePreviewPoint = null
    measureStatusHint.value = 'Ведите мышь ко 2-й точке. Клик — зафиксировать. Esc — отмена.'
    if (faceGeom) measurementFaceGeometries.push(faceGeom)
    logger.info(
      'Viewer3D',
      `MeasureClick#${clickId} distance point added: p=${formatVec3(point)}, total=${measurementPoints.length}`
    )
  }
  if (measurementPoints.length === 2) {
    const tGraphics = performance.now()
    updateMeasurementGraphics()
    logger.info(
      'Viewer3D',
      `MeasureClick#${clickId} graphics updated: ${(performance.now() - tGraphics).toFixed(1)} ms`
    )
    if (measureTypeRef.value === 'distance') {
      saveDistanceMeasurement()
    }
  } else {
    refreshMeasurementReferenceFaceHighlights()
  }
  logger.info(
    'Viewer3D',
    `MeasureClick#${clickId} done distance: points=${measurementPoints.length}, normals=${measurementPointNormals.length}, ${(performance.now() - clickT0).toFixed(1)} ms`
  )
}

const AXIS_COLOR_X = 0xff0000
const AXIS_COLOR_Y = 0x00ff00
const AXIS_COLOR_Z = 0x0000ff
const MEASURE_PLANE_NORMAL = new THREE.Vector3(0, 1, 0)

let radiusOrDiameterResult: { center: THREE.Vector3; radius: number; normal: THREE.Vector3; isDiameter?: boolean } | null = null
let arcResult: { path: THREE.Vector3[]; length: number } | null = null
let arcFirstPoint: THREE.Vector3 | null = null
let arcMesh: THREE.Mesh | null = null
let holeCenterFirst: THREE.Vector3 | null = null
let holeCenterFirstModelId: string | null = null
let holeCenterFirstMeshUuid: string | null = null
let holeCenterFirstLocal: SavedVec3 | null = null
let firstClickHole: { center: THREE.Vector3; radius: number; normal: THREE.Vector3 } | null = null
let secondHoleResult: { center: THREE.Vector3; radius: number; normal: THREE.Vector3 } | null = null
let firstClickHoleModelId: string | null = null
let firstClickHoleMeshUuid: string | null = null
let firstClickHoleLocalCenter: SavedVec3 | null = null
let firstClickHoleLocalNormal: SavedVec3 | null = null
let cadLinearPlanePoint: THREE.Vector3 | null = null
let cadLinearPlaneNormal: THREE.Vector3 | null = null
let cadLinearPlaneModelId: string | null = null
let cadLinearPlaneLocalPoint: SavedVec3 | null = null
let cadLinearPlaneLocalNormal: SavedVec3 | null = null
type CadLinearPickTarget = 'plane1' | 'plane2' | 'display' | null
const cadLinearPickTarget = ref<CadLinearPickTarget>(null)
const cadLinearPlane1 = ref<AssemblyPlaneSelection | null>(null)
const cadLinearPlane2 = ref<AssemblyPlaneSelection | null>(null)
const cadLinearDisplayPlane = ref<AssemblyPlaneSelection | null>(null)
const cadLinearStatus = ref('')
let diameterSecondLabelEl: HTMLDivElement | null = null
let measureClickSeq = 0

function formatVec3(v: THREE.Vector3): string {
  return `${v.x.toFixed(1)},${v.y.toFixed(1)},${v.z.toFixed(1)}`
}

/** Fit circle to coplanar points (in plane with given normal). Returns center (world) and radius. */
function fitCircleToPoints(points: THREE.Vector3[], normal: THREE.Vector3): { center: THREE.Vector3; radius: number } | null {
  if (points.length < 3) return null
  const n = normal.clone().normalize()
  const origin = points[0].clone()
  const u = new THREE.Vector3().subVectors(points[1], points[0]).normalize()
  const v = new THREE.Vector3().crossVectors(n, u).normalize()
  const pts2d: { x: number; y: number }[] = []
  for (const p of points) {
    const d = p.clone().sub(origin)
    pts2d.push({ x: d.dot(u), y: d.dot(v) })
  }
  const N = pts2d.length
  let sx = 0, sy = 0
  for (const q of pts2d) {
    sx += q.x
    sy += q.y
  }
  const cx = sx / N
  const cy = sy / N
  let r2 = 0
  for (const q of pts2d) r2 += (q.x - cx) ** 2 + (q.y - cy) ** 2
  const radius = Math.sqrt(r2 / N)
  const center = origin.clone().add(u.multiplyScalar(cx)).add(v.multiplyScalar(cy))
  return { center, radius }
}

/** Collect world positions of vertices from hit face and adjacent faces (1 ring). */
function getVerticesAroundFace(mesh: THREE.Mesh, faceIndex: number): THREE.Vector3[] {
  const geom = mesh.geometry
  const pos = geom.attributes.position
  const index = geom.index
  const numFaces = index ? index.count / 3 : pos.count / 3
  const getV = (i: number) => {
    const j = index ? index.getX(i)! : i
    return new THREE.Vector3(pos.getX(j), pos.getY(j), pos.getZ(j)).applyMatrix4(mesh.matrixWorld)
  }
  const getFaceVerts = (fi: number) => {
    if (index) return [getV(fi * 3), getV(fi * 3 + 1), getV(fi * 3 + 2)]
    return [getV(fi * 3), getV(fi * 3 + 1), getV(fi * 3 + 2)]
  }
  const edgeKey = (a: number, b: number) => a < b ? `${a},${b}` : `${b},${a}`
  const edgeToFaces = new Map<string, number[]>()
  for (let fi = 0; fi < numFaces; fi++) {
    const [a, b, c] = index ? [index.getX(fi * 3)!, index.getX(fi * 3 + 1)!, index.getX(fi * 3 + 2)!] : [fi * 3, fi * 3 + 1, fi * 3 + 2]
    for (const [x, y] of [[a, b], [b, c], [c, a]] as [number, number][]) {
      const k = edgeKey(x, y)
      if (!edgeToFaces.has(k)) edgeToFaces.set(k, [])
      edgeToFaces.get(k)!.push(fi)
    }
  }
  const seen = new Set<number>([faceIndex])
  const queue = [faceIndex]
  while (queue.length > 0) {
    const fi = queue.shift()!
    const [a, b, c] = index ? [index.getX(fi * 3)!, index.getX(fi * 3 + 1)!, index.getX(fi * 3 + 2)!] : [fi * 3, fi * 3 + 1, fi * 3 + 2]
    for (const [x, y] of [[a, b], [b, c], [c, a]] as [number, number][]) {
      const k = edgeKey(x, y)
      const faces = edgeToFaces.get(k) || []
      for (const nf of faces) {
        if (!seen.has(nf)) {
          seen.add(nf)
          queue.push(nf)
        }
      }
    }
  }
  const out: THREE.Vector3[] = []
  seen.forEach(fi => getFaceVerts(fi).forEach(v => out.push(v)))
  return out
}

/** If point is near a boundary loop (hole rim), return circle fit { center, radius, normal }. */
function getHoverHoleInfo(mesh: THREE.Mesh, point: THREE.Vector3): { center: THREE.Vector3; radius: number; normal: THREE.Vector3 } | null {
  const loops = getBoundaryLoops(mesh)
  if (loops.length === 0) return null
  const tol = 2
  let best: { center: THREE.Vector3; radius: number; normal: THREE.Vector3; dist: number } | null = null
  for (const loop of loops) {
    if (loop.length < 3) continue
    const n = new THREE.Vector3().crossVectors(
      loop[1].clone().sub(loop[0]),
      loop[2].clone().sub(loop[0])
    ).normalize()
    const fit = fitCircleToPoints(loop, n)
    if (!fit || fit.radius < 0.1) continue
    const toPlane = Math.abs(point.clone().sub(fit.center).dot(n))
    const proj = point.clone().sub(n.clone().multiplyScalar(point.clone().sub(fit.center).dot(n)))
    const dToCenter = proj.distanceTo(fit.center)
    const rimDist = Math.abs(dToCenter - fit.radius)
    if (toPlane <= fit.radius * 0.5 && rimDist <= Math.max(fit.radius * 0.2, tol)) {
      const dist = toPlane + rimDist
      if (!best || dist < best.dist) best = { ...fit, normal: n, dist }
    }
  }
  return best ? { center: best.center, radius: best.radius, normal: best.normal } : null
}

/** Fit circle to vertices around face; if good, return { center, radius }. */
function getHoverRadiusInfo(mesh: THREE.Mesh, faceIndex: number, normal: THREE.Vector3): { center: THREE.Vector3; radius: number } | null {
  const verts = getVerticesAroundFace(mesh, faceIndex)
  const fit = fitCircleToPoints(verts, normal)
  if (!fit || fit.radius < 0.5) return null
  return fit
}

/** Check if cylindrical surface (center, radius, normal) is a hole by raycasting: ray from center along -normal; if we hit mesh in a plausible range, we're inside material (hole). */
function isCylinderAHole(
  mesh: THREE.Mesh,
  center: THREE.Vector3,
  radius: number,
  normal: THREE.Vector3,
  raycaster: THREE.Raycaster,
): boolean {
  const origin = center.clone()
  const dir = normal.clone().negate()
  raycaster.set(origin, dir)
  raycaster.far = radius * 25
  const hits = raycaster.intersectObject(mesh, true)
  if (hits.length === 0) return false
  const hit = hits[0]
  if (hit.distance < radius * 0.1) return false
  if (hit.distance > radius * 20) return false
  return true
}

const CYLINDER_RADIUS_TOL = 0.12

/** Get all face indices that belong to the same cylindrical zone (same circle fit). Returns merged BufferGeometry in world coords or null. */
function getCylindricalZoneGeometry(mesh: THREE.Mesh, faceIndex: number, normal: THREE.Vector3): THREE.BufferGeometry | null {
  const t0 = performance.now()
  const verts = getVerticesAroundFace(mesh, faceIndex)
  const fit = fitCircleToPoints(verts, normal.clone())
  if (!fit || fit.radius < 0.5) return null
  const geom = mesh.geometry
  const pos = geom.attributes.position
  const index = geom.index
  const numFaces = index ? index.count / 3 : pos.count / 3
  const getWorld = (posIdx: number) =>
    new THREE.Vector3(pos.getX(posIdx), pos.getY(posIdx), pos.getZ(posIdx)).applyMatrix4(mesh.matrixWorld)
  const getFaceVerts = (fi: number) => {
    const a = index ? index.getX(fi * 3)! : fi * 3
    const b = index ? index.getX(fi * 3 + 1)! : fi * 3 + 1
    const c = index ? index.getX(fi * 3 + 2)! : fi * 3 + 2
    return [getWorld(a), getWorld(b), getWorld(c)]
  }
  const edgeKey = (a: number, b: number) => (a < b ? `${a},${b}` : `${b},${a}`)
  const edgeToFaces = new Map<string, number[]>()
  for (let fi = 0; fi < numFaces; fi++) {
    const [a, b, c] = index ? [index.getX(fi * 3)!, index.getX(fi * 3 + 1)!, index.getX(fi * 3 + 2)!] : [fi * 3, fi * 3 + 1, fi * 3 + 2]
    for (const [x, y] of [[a, b], [b, c], [c, a]] as [number, number][]) {
      const k = edgeKey(x, y)
      if (!edgeToFaces.has(k)) edgeToFaces.set(k, [])
      edgeToFaces.get(k)!.push(fi)
    }
  }
  const center = fit.center
  const n = normal.clone().normalize()
  const radius = fit.radius
  const tol = radius * CYLINDER_RADIUS_TOL
  const faceFitsCircle = (fi: number): boolean => {
    const [p0, p1, p2] = getFaceVerts(fi)
    for (const p of [p0, p1, p2]) {
      const proj = p.clone().sub(n.clone().multiplyScalar(p.clone().sub(center).dot(n)))
      const d = proj.distanceTo(center)
      if (Math.abs(d - radius) > tol) return false
    }
    return true
  }
  const zone = new Set<number>([faceIndex])
  const queue = [faceIndex]
  while (queue.length > 0) {
    const fi = queue.shift()!
    const [a, b, c] = index ? [index.getX(fi * 3)!, index.getX(fi * 3 + 1)!, index.getX(fi * 3 + 2)!] : [fi * 3, fi * 3 + 1, fi * 3 + 2]
    for (const [x, y] of [[a, b], [b, c], [c, a]] as [number, number][]) {
      const k = edgeKey(x, y)
      for (const nf of edgeToFaces.get(k) || []) {
        if (zone.has(nf)) continue
        if (!faceFitsCircle(nf)) continue
        zone.add(nf)
        queue.push(nf)
      }
    }
  }
  const positions: number[] = []
  zone.forEach((fi) => {
    const [p0, p1, p2] = getFaceVerts(fi)
    positions.push(p0.x, p0.y, p0.z, p1.x, p1.y, p1.z, p2.x, p2.y, p2.z)
  })
  if (positions.length === 0) return null
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  g.computeVertexNormals()
  const ms = performance.now() - t0
  if (ms > 20) console.log('[getCylindricalZoneGeometry]', ms.toFixed(1), 'ms, numFaces:', numFaces, 'zoneSize:', zone.size)
  return g
}

/** Get boundary loops (edges with only one adjacent face). Each loop = array of world positions. */
function getBoundaryLoops(mesh: THREE.Mesh): THREE.Vector3[][] {
  const t0 = performance.now()
  const geom = mesh.geometry
  const pos = geom.attributes.position
  const index = geom.index
  const getWorld = (i: number) => {
    const j = index ? index.getX(i)! : i
    return new THREE.Vector3(pos.getX(j), pos.getY(j), pos.getZ(j)).applyMatrix4(mesh.matrixWorld)
  }
  const edgeKey = (a: number, b: number) => a < b ? `${a},${b}` : `${b},${a}`
  const edgeFaces = new Map<string, number[]>()
  const numFaces = index ? index.count / 3 : pos.count / 3
  for (let fi = 0; fi < numFaces; fi++) {
    const [a, b, c] = index ? [index.getX(fi * 3)!, index.getX(fi * 3 + 1)!, index.getX(fi * 3 + 2)!] : [fi * 3, fi * 3 + 1, fi * 3 + 2]
    for (const [x, y] of [[a, b], [b, c], [c, a]] as [number, number][]) {
      const k = edgeKey(x, y)
      if (!edgeFaces.has(k)) edgeFaces.set(k, [])
      edgeFaces.get(k)!.push(fi)
    }
  }
  const boundaryEdges: [number, number][] = []
  edgeFaces.forEach((faces, k) => {
    if (faces.length === 1) {
      const [a, b] = k.split(',').map(Number)
      boundaryEdges.push([a, b])
    }
  })
  const adj = new Map<number, number[]>()
  for (const [a, b] of boundaryEdges) {
    if (!adj.has(a)) adj.set(a, [])
    adj.get(a)!.push(b)
    if (!adj.has(b)) adj.set(b, [])
    adj.get(b)!.push(a)
  }
  const visited = new Set<string>()
  const loops: THREE.Vector3[][] = []
  for (const [start, next] of boundaryEdges) {
    const key = edgeKey(start, next)
    if (visited.has(key)) continue
    const loop: number[] = [start, next]
    visited.add(edgeKey(start, next))
    let cur = next
    while (cur !== start && loop.length < 10000) {
      const neighbors = adj.get(cur)!.filter(n => n !== loop[loop.length - 2])
      const nextNode = neighbors.find(n => !visited.has(edgeKey(cur, n)))
      if (!nextNode) break
      visited.add(edgeKey(cur, nextNode))
      loop.push(nextNode)
      cur = nextNode
    }
    if (cur === start && loop.length >= 3) {
      loops.push(loop.map(i => getWorld(i)))
    }
  }
  const ms = performance.now() - t0
  if (ms > 20) console.log('[getBoundaryLoops]', ms.toFixed(1), 'ms, numFaces:', numFaces, 'loops:', loops.length)
  return loops
}

/** Get hole (circle) from mesh and a point near the hole rim. Returns { center, radius, normal } or null. */
function getHoleFromHit(mesh: THREE.Mesh, point: THREE.Vector3): { center: THREE.Vector3; radius: number; normal: THREE.Vector3 } | null {
  const loops = getBoundaryLoops(mesh)
  if (loops.length === 0) return null
  let bestLoop = loops[0]
  let bestDist = point.distanceTo(loops[0].reduce((a, p) => a.add(p), new THREE.Vector3(0, 0, 0)).divideScalar(loops[0].length))
  for (const loop of loops) {
    const cen = loop.reduce((a, p) => a.add(p.clone()), new THREE.Vector3(0, 0, 0)).divideScalar(loop.length)
    const d = point.distanceTo(cen)
    if (d < bestDist) {
      bestDist = d
      bestLoop = loop
    }
  }
  const n = bestLoop.length >= 3
    ? new THREE.Vector3().crossVectors(
        bestLoop[1].clone().sub(bestLoop[0]),
        bestLoop[2].clone().sub(bestLoop[0])
      ).normalize()
    : new THREE.Vector3(0, 1, 0)
  const fit = fitCircleToPoints(bestLoop, n)
  if (!fit) return null
  return { center: fit.center, radius: fit.radius, normal: n }
}

/** Shortest path on mesh between two world points (Dijkstra along edges). */
function shortestPathOnMesh(mesh: THREE.Mesh, from: THREE.Vector3, to: THREE.Vector3): { path: THREE.Vector3[]; length: number } | null {
  const geom = mesh.geometry
  const pos = geom.attributes.position
  const index = geom.index
  const numFaces = index ? index.count / 3 : pos.count / 3
  const getWorld = (i: number) => {
    const j = index ? index.getX(i)! : i
    return new THREE.Vector3(pos.getX(j), pos.getY(j), pos.getZ(j)).applyMatrix4(mesh.matrixWorld)
  }
  const vertices = new Map<string, number>()
  const posIndexBySeq: number[] = []
  const getVertIdx = (a: number) => {
    const k = String(a)
    if (!vertices.has(k)) {
      vertices.set(k, vertices.size)
      posIndexBySeq.push(a)
    }
    return vertices.get(k)!
  }
  for (let fi = 0; fi < numFaces; fi++) {
    const [a, b, c] = index ? [index.getX(fi * 3)!, index.getX(fi * 3 + 1)!, index.getX(fi * 3 + 2)!] : [fi * 3, fi * 3 + 1, fi * 3 + 2]
    getVertIdx(a)
    getVertIdx(b)
    getVertIdx(c)
  }
  const worldByIdx = posIndexBySeq.map(i => getWorld(i))
  const adjList = new Map<number, { to: number; len: number }[]>()
  for (let fi = 0; fi < numFaces; fi++) {
    const [a, b, c] = index ? [index.getX(fi * 3)!, index.getX(fi * 3 + 1)!, index.getX(fi * 3 + 2)!] : [fi * 3, fi * 3 + 1, fi * 3 + 2]
    const va = getWorld(a)
    const vb = getWorld(b)
    const vc = getWorld(c)
    const i = getVertIdx(a)
    const j = getVertIdx(b)
    const k = getVertIdx(c)
    if (!adjList.has(i)) adjList.set(i, [])
    adjList.get(i)!.push({ to: j, len: va.distanceTo(vb) })
    adjList.get(i)!.push({ to: k, len: va.distanceTo(vc) })
    if (!adjList.has(j)) adjList.set(j, [])
    adjList.get(j)!.push({ to: i, len: va.distanceTo(vb) })
    adjList.get(j)!.push({ to: k, len: vb.distanceTo(vc) })
    if (!adjList.has(k)) adjList.set(k, [])
    adjList.get(k)!.push({ to: i, len: va.distanceTo(vc) })
    adjList.get(k)!.push({ to: j, len: vb.distanceTo(vc) })
  }
  let startIdx = 0
  let endIdx = 0
  let bestStart = Infinity
  let bestEnd = Infinity
  worldByIdx.forEach((w, idx) => {
    const d1 = w.distanceTo(from)
    const d2 = w.distanceTo(to)
    if (d1 < bestStart) {
      bestStart = d1
      startIdx = idx
    }
    if (d2 < bestEnd) {
      bestEnd = d2
      endIdx = idx
    }
  })
  const dist: number[] = []
  const prev: (number | null)[] = []
  worldByIdx.forEach((_, i) => {
    dist[i] = Infinity
    prev[i] = null
  })
  dist[startIdx] = 0
  const heap: { idx: number; d: number }[] = [{ idx: startIdx, d: 0 }]
  while (heap.length > 0) {
    heap.sort((a, b) => a.d - b.d)
    const { idx: u, d: du } = heap.shift()!
    if (du > dist[u]) continue
    if (u === endIdx) break
    for (const { to: v, len } of adjList.get(u) || []) {
      const alt = dist[u] + len
      if (alt < dist[v]) {
        dist[v] = alt
        prev[v] = u
        heap.push({ idx: v, d: alt })
      }
    }
  }
  if (prev[endIdx] === null && endIdx !== startIdx) return null
  const pathIdx: number[] = []
  let cur: number | null = endIdx
  while (cur !== null) {
    pathIdx.unshift(cur)
    cur = prev[cur]
  }
  const path = pathIdx.map(i => worldByIdx[i].clone())
  const length = dist[endIdx]
  return { path, length }
}

function updateMeasurementGraphics() {
  const t0 = performance.now()
  logger.debug(
    'Viewer3D',
    `updateMeasurementGraphics start: type=${measureTypeRef.value}, points=${measurementPoints.length}, faces=${measurementFaceGeometries.length}`
  )
  if (measurementLine) {
    measureGroup.remove(measurementLine)
    measurementLine.geometry.dispose()
    ;(measurementLine.material as THREE.Material).dispose()
    measurementLine = null
  }
  for (const line of measurementTriangleLines) {
    measureGroup.remove(line)
    line.geometry.dispose()
    ;(line.material as THREE.Material).dispose()
  }
  measurementTriangleLines = []
  if (measurementPerpLine) {
    measureGroup.remove(measurementPerpLine)
    measurementPerpLine.geometry.dispose()
    ;(measurementPerpLine.material as THREE.Material).dispose()
    measurementPerpLine = null
  }
  if (measurementCircleMesh) {
    measureGroup.remove(measurementCircleMesh)
    measurementCircleMesh.geometry.dispose()
    ;(measurementCircleMesh.material as THREE.Material).dispose()
    measurementCircleMesh = null
  }
  if (measurementCircleMesh2) {
    measureGroup.remove(measurementCircleMesh2)
    measurementCircleMesh2.geometry.dispose()
    ;(measurementCircleMesh2.material as THREE.Material).dispose()
    measurementCircleMesh2 = null
  }
  if (measurementArcPathLine) {
    measureGroup.remove(measurementArcPathLine)
    measurementArcPathLine.geometry.dispose()
    ;(measurementArcPathLine.material as THREE.Material).dispose()
    measurementArcPathLine = null
  }
  if (radiusOrDiameterResult) {
    const { center, radius, normal } = radiusOrDiameterResult
    const segs = 64
    const pts: THREE.Vector3[] = []
    const u = new THREE.Vector3().crossVectors(normal, new THREE.Vector3(1, 0, 0)).normalize()
    if (u.lengthSq() < 0.01) u.crossVectors(normal, new THREE.Vector3(0, 1, 0)).normalize()
    const v = new THREE.Vector3().crossVectors(normal, u).normalize()
    for (let i = 0; i <= segs; i++) {
      const t = (i / segs) * Math.PI * 2
      pts.push(center.clone().add(u.clone().multiplyScalar(radius * Math.cos(t))).add(v.clone().multiplyScalar(radius * Math.sin(t))))
    }
    const geom = new THREE.BufferGeometry().setFromPoints(pts)
    measurementCircleMesh = new THREE.LineLoop(geom, new THREE.LineBasicMaterial({ color: 0x00ff88 }))
    measureGroup.add(measurementCircleMesh)
  }
  if (secondHoleResult) {
    const { center, radius, normal } = secondHoleResult
    const segs = 64
    const pts: THREE.Vector3[] = []
    const u = new THREE.Vector3().crossVectors(normal, new THREE.Vector3(1, 0, 0)).normalize()
    if (u.lengthSq() < 0.01) u.crossVectors(normal, new THREE.Vector3(0, 1, 0)).normalize()
    const v = new THREE.Vector3().crossVectors(normal, u).normalize()
    for (let i = 0; i <= segs; i++) {
      const t = (i / segs) * Math.PI * 2
      pts.push(center.clone().add(u.clone().multiplyScalar(radius * Math.cos(t))).add(v.clone().multiplyScalar(radius * Math.sin(t))))
    }
    const geom = new THREE.BufferGeometry().setFromPoints(pts)
    measurementCircleMesh2 = new THREE.LineLoop(geom, new THREE.LineBasicMaterial({ color: 0x00ff88 }))
    measureGroup.add(measurementCircleMesh2)
  }
  if (arcResult && arcResult.path.length >= 2) {
    const geom = new THREE.BufferGeometry().setFromPoints(arcResult.path)
    measurementArcPathLine = new THREE.Line(geom, new THREE.LineBasicMaterial({ color: 0xff8800 }))
    measureGroup.add(measurementArcPathLine)
  }
  if (
    measureTypeRef.value !== 'distance'
    && measureTypeRef.value !== 'hole-center-distance'
    && measureTypeRef.value !== 'cad-linear'
    && !(measureTypeRef.value === 'diameter' && measurementPoints.length === 2)
  ) {
    logger.info('Viewer3D', `updateMeasurementGraphics done (non-distance): ${(performance.now() - t0).toFixed(1)} ms`)
    return
  }
  if (measurementPoints.length === 1 && measurePreviewPoint && measureTypeRef.value === 'distance') {
    const A = measurementPoints[0]
    const B = measurePreviewPoint
    const geom = new THREE.BufferGeometry().setFromPoints([A, B])
    const mat = new THREE.LineDashedMaterial({
      color: 0x7fc2ff,
      dashSize: 6,
      gapSize: 4,
      depthTest: false,
      transparent: true,
      opacity: 0.95,
    })
    measurementLine = new THREE.Line(geom, mat)
    measurementLine.computeLineDistances()
    measurementLine.renderOrder = 1000
    measureGroup.add(measurementLine)
    logger.debug('Viewer3D', `updateMeasurementGraphics done (preview): ${(performance.now() - t0).toFixed(1)} ms`)
    return
  }
  if (measurementPoints.length !== 2) {
    logger.debug('Viewer3D', `updateMeasurementGraphics done (points!=2): ${(performance.now() - t0).toFixed(1)} ms`)
    return
  }
  const [A, B] = measurementPoints
  if (measureTypeRef.value === 'hole-center-distance') {
    const geom = new THREE.BufferGeometry().setFromPoints([A, B])
    const mat = new THREE.LineBasicMaterial({ color: AXIS_COLOR_X })
    measurementLine = new THREE.Line(geom, mat)
    measureGroup.add(measurementLine)
    logger.info('Viewer3D', `updateMeasurementGraphics done (hole-center): ${(performance.now() - t0).toFixed(1)} ms`)
    return
  }
  if (measureTypeRef.value === 'distance') {
    logger.debug('Viewer3D', `updateMeasurementGraphics done (distance saved-only): ${(performance.now() - t0).toFixed(1)} ms`)
    return
  }
  if (measureTypeRef.value === 'cad-linear') {
    const nA = measurementPointNormals[0] ?? null
    const nB = measurementPointNormals[1] ?? null
    const strict = projectPerpendicularByNormals(A, B, nA, nB)
    const srcA = strict ? strict.projected : A
    const srcB = strict ? strict.otherPoint : B
    const n = (nB ?? nA ?? new THREE.Vector3(0, 1, 0)).clone().normalize()
    const dir = srcB.clone().sub(srcA).normalize()
    let offsetDir = new THREE.Vector3().crossVectors(dir, n).normalize()
    if (offsetDir.lengthSq() < 0.01) offsetDir = new THREE.Vector3(0, 0, 1)
    offsetDir = orientOffsetDirForScreen(offsetDir, srcA.clone().add(srcB).multiplyScalar(0.5))
    const off = Math.max(2, dimLineOffsetMm.value)
    const pA = srcA.clone().add(offsetDir.clone().multiplyScalar(off))
    const pB = srcB.clone().add(offsetDir.clone().multiplyScalar(off))
    const dimMat = new THREE.LineBasicMaterial({ color: DIM_GOST_COLOR })
    const extA = new THREE.Line(new THREE.BufferGeometry().setFromPoints([srcA, pA]), dimMat)
    const extB = new THREE.Line(new THREE.BufferGeometry().setFromPoints([srcB, pB]), dimMat.clone())
    const dim = new THREE.Line(new THREE.BufferGeometry().setFromPoints([pA, pB]), dimMat.clone())
    measureGroup.add(extA, extB, dim)
    measurementTriangleLines.push(extA, extB, dim)
    const arrow = Math.max(3, dimArrowSizeMm.value)
    addGostArrowHead(measureGroup, pA, pB.clone().sub(pA), DIM_GOST_COLOR, arrow)
    addGostArrowHead(measureGroup, pB, pA.clone().sub(pB), DIM_GOST_COLOR, arrow)
  }
  logger.info('Viewer3D', `updateMeasurementGraphics done: ${(performance.now() - t0).toFixed(1)} ms`)
}

function clearMeasurements() {
  if (measurementLine) {
    measureGroup.remove(measurementLine)
    measurementLine.geometry.dispose()
    ;(measurementLine.material as THREE.Material).dispose()
    measurementLine = null
  }
  for (const line of measurementTriangleLines) {
    measureGroup.remove(line)
    line.geometry.dispose()
    ;(line.material as THREE.Material).dispose()
  }
  measurementTriangleLines = []
  measurementPoints = []
  measurementPointNormals = []
  measurementPointModelIds = []
  measurementPointMeshUuids = []
  measurementPointLocals = []
  measurementPointNormalLocals = []
  for (const g of measurementFaceGeometries) g.dispose()
  measurementFaceGeometries = []
  clearMeasurementPlanesGroup()
  refreshMeasurementReferenceFaceHighlights()
  if (measurementPerpLine) {
    measureGroup.remove(measurementPerpLine)
    measurementPerpLine.geometry.dispose()
    ;(measurementPerpLine.material as THREE.Material).dispose()
    measurementPerpLine = null
  }
  if (measurementCircleMesh) {
    measureGroup.remove(measurementCircleMesh)
    measurementCircleMesh.geometry.dispose()
    ;(measurementCircleMesh.material as THREE.Material).dispose()
    measurementCircleMesh = null
  }
  if (measurementCircleMesh2) {
    measureGroup.remove(measurementCircleMesh2)
    measurementCircleMesh2.geometry.dispose()
    ;(measurementCircleMesh2.material as THREE.Material).dispose()
    measurementCircleMesh2 = null
  }
  if (measurementArcPathLine) {
    measureGroup.remove(measurementArcPathLine)
    measurementArcPathLine.geometry.dispose()
    ;(measurementArcPathLine.material as THREE.Material).dispose()
    measurementArcPathLine = null
  }
  radiusOrDiameterResult = null
  arcResult = null
  arcFirstPoint = null
  arcMesh = null
  holeCenterFirst = null
  holeCenterFirstModelId = null
  holeCenterFirstMeshUuid = null
  holeCenterFirstLocal = null
  firstClickHole = null
  secondHoleResult = null
  firstClickHoleModelId = null
  firstClickHoleMeshUuid = null
  firstClickHoleLocalCenter = null
  firstClickHoleLocalNormal = null
  cadLinearPlanePoint = null
  cadLinearPlaneNormal = null
  cadLinearPlaneModelId = null
  cadLinearPlaneLocalPoint = null
  cadLinearPlaneLocalNormal = null
  measurePreviewPoint = null
  if (measurementLabelEl) measurementLabelEl.style.display = 'none'
  if (diameterSecondLabelEl) diameterSecondLabelEl.style.display = 'none'
  if (measurementLabelEl0) measurementLabelEl0.style.display = 'none'
  if (measurementLabelEl1) measurementLabelEl1.style.display = 'none'
  if (measurementLabelEl2) measurementLabelEl2.style.display = 'none'
  if (measurementPerpLabelEl) measurementPerpLabelEl.style.display = 'none'
  if (measurementExtraLabelEl) measurementExtraLabelEl.style.display = 'none'
}

function setMeasureMode(enabled: boolean) {
  logger.info('Viewer3D', `setMeasureMode вызван: enabled=${enabled}`)
  measureModeRef.value = enabled
  hoverDirty = true
  if (!enabled) {
    clearMeasurements()
    cadLinearPickTarget.value = null
    measureStatusHint.value = ''
  } else if (measureTypeRef.value === 'distance') {
    measureStatusHint.value = 'Кликните 1-ю точку на модели.'
  } else if (measureTypeRef.value === 'cad-linear') {
    measureStatusHint.value = cadLinearStatus.value || 'Кликните 1-ю параллельную грань.'
  }
  logger.info('Viewer3D', `Режим измерения: ${enabled ? 'вкл' : 'выкл'}`)
}

function setMeasureSnapMode(mode: MeasureSnapMode) {
  measureSnapMode = mode
  emit('update:measureSnapMode', mode)
}

function getMeasureSnapMode(): MeasureSnapMode {
  return 'intersection'
}

function setMeasureType(type: MeasureType) {
  measureTypeRef.value = type
  emit('update:measureType', type)
  measurePreviewPoint = null
  if (type !== 'distance') {
    measurementPoints = []
    measurementPointNormals = []
    measurementPointModelIds = []
    measurementPointMeshUuids = []
    measurementPointLocals = []
    measurementPointNormalLocals = []
    for (const g of measurementFaceGeometries) g.dispose()
    measurementFaceGeometries = []
  }
  radiusOrDiameterResult = null
  arcResult = null
  arcFirstPoint = null
  arcMesh = null
  holeCenterFirst = null
  holeCenterFirstModelId = null
  holeCenterFirstMeshUuid = null
  holeCenterFirstLocal = null
  firstClickHole = null
  secondHoleResult = null
  firstClickHoleModelId = null
  firstClickHoleMeshUuid = null
  firstClickHoleLocalCenter = null
  firstClickHoleLocalNormal = null
  cadLinearPlanePoint = null
  cadLinearPlaneNormal = null
  cadLinearPlaneModelId = null
  cadLinearPlaneLocalPoint = null
  cadLinearPlaneLocalNormal = null
  if (type === 'cad-linear') {
    beginNextCadLinearDimension()
  } else {
    clearCadLinearPicks()
    cadLinearStatus.value = ''
    if (type === 'distance' && measureModeRef.value) {
      measureStatusHint.value = 'Кликните 1-ю точку на модели.'
    } else {
      measureStatusHint.value = ''
    }
  }
  updateMeasurementGraphics()
}

function meshVertexWorld(mesh: THREE.Mesh, vi: number, out: THREE.Vector3): THREE.Vector3 {
  const pos = mesh.geometry.attributes.position
  return out.set(pos.getX(vi), pos.getY(vi), pos.getZ(vi)).applyMatrix4(mesh.matrixWorld)
}

function snapSearchRadiusWorld(mesh: THREE.Mesh): number {
  const box = new THREE.Box3().setFromObject(mesh)
  const diag = box.getSize(new THREE.Vector3()).length()
  return Math.max(10, Math.min(150, diag * 0.02))
}

function pushSnapUnique(out: SnapCandidate[], point: THREE.Vector3, kind: SnapCandidate['kind'], seen: Set<string>) {
  const key = `${point.x.toFixed(3)}|${point.y.toFixed(3)}|${point.z.toFixed(3)}|${kind}`
  if (seen.has(key)) return
  seen.add(key)
  out.push({ point: point.clone(), kind })
}

function collectCoplanarPatchSnap(mesh: THREE.Mesh, faceIndex: number, out: SnapCandidate[], seen: Set<string>) {
  const patch = getCoplanarFaceGeometry(mesh, faceIndex)
  if (!patch) return
  const attr = patch.attributes.position
  if (!attr) {
    patch.dispose()
    return
  }
  const v = new THREE.Vector3()
  for (let i = 0; i < attr.count; i++) {
    v.set(attr.getX(i), attr.getY(i), attr.getZ(i))
    pushSnapUnique(out, v, 'vertex', seen)
  }
  patch.dispose()
}

function collectNearbyMeshSnap(mesh: THREE.Mesh, hit: THREE.Intersection, out: SnapCandidate[], seen: Set<string>) {
  const face = hit.face!
  const pos = mesh.geometry.attributes.position
  if (!pos) return
  const faceIndex =
    typeof (hit as THREE.Intersection & { faceIndex?: number }).faceIndex === 'number'
      ? (hit as THREE.Intersection & { faceIndex: number }).faceIndex
      : Math.floor(face.a / 3)
  const index = mesh.geometry.index
  const numFaces = index ? index.count / 3 : pos.count / 3
  const hitPoint = hit.point
  const radius = snapSearchRadiusWorld(mesh)

  if (numFaces > 30000) {
    collectCoplanarPatchSnap(mesh, faceIndex, out, seen)
    return
  }

  const vA = new THREE.Vector3()
  const vB = new THREE.Vector3()
  const vC = new THREE.Vector3()
  const center = new THREE.Vector3()
  const edgeSeen = new Set<string>()

  for (let fi = 0; fi < numFaces; fi++) {
    let a: number
    let b: number
    let c: number
    if (index) {
      a = index.getX(fi * 3)!
      b = index.getX(fi * 3 + 1)!
      c = index.getX(fi * 3 + 2)!
    } else {
      a = fi * 3
      b = fi * 3 + 1
      c = fi * 3 + 2
    }
    meshVertexWorld(mesh, a, vA)
    meshVertexWorld(mesh, b, vB)
    meshVertexWorld(mesh, c, vC)
    center.copy(vA).add(vB).add(vC).multiplyScalar(1 / 3)
    if (center.distanceTo(hitPoint) > radius * 1.25) continue

    pushSnapUnique(out, vA, 'vertex', seen)
    pushSnapUnique(out, vB, 'vertex', seen)
    pushSnapUnique(out, vC, 'vertex', seen)

    const edges: [number, number][] = [
      [a, b],
      [b, c],
      [c, a],
    ]
    for (const [i, j] of edges) {
      const key = i < j ? `${i},${j}` : `${j},${i}`
      if (edgeSeen.has(key)) continue
      edgeSeen.add(key)
      meshVertexWorld(mesh, i, vA)
      meshVertexWorld(mesh, j, vB)
      pushSnapUnique(out, vA.clone().add(vB).multiplyScalar(0.5), 'edge', seen)
      snapSeg.set(vA, vB)
      snapSeg.closestPointToPoint(hitPoint, true, snapClosest)
      pushSnapUnique(out, snapClosest, 'edge', seen)
    }
  }
}

/** Вершины, рёбра и грань у курсора (приоритет: вершина → ребро → грань). */
function getSnapCandidates(hit: THREE.Intersection): SnapCandidate[] {
  const mesh = hit.object as THREE.Mesh
  const face = hit.face!
  const pos = mesh.geometry.attributes.position
  if (!pos) return [{ point: hit.point.clone(), kind: 'surface' }]
  const seen = new Set<string>()
  const out: SnapCandidate[] = []
  const vA = new THREE.Vector3()
  const vB = new THREE.Vector3()
  const vC = new THREE.Vector3()
  meshVertexWorld(mesh, face.a, vA)
  meshVertexWorld(mesh, face.b, vB)
  meshVertexWorld(mesh, face.c, vC)
  const center = vA.clone().add(vB).add(vC).multiplyScalar(1 / 3)
  pushSnapUnique(out, hit.point, 'surface', seen)
  pushSnapUnique(out, vA, 'vertex', seen)
  pushSnapUnique(out, vB, 'vertex', seen)
  pushSnapUnique(out, vC, 'vertex', seen)
  pushSnapUnique(out, center, 'face', seen)
  pushSnapUnique(out, vA.clone().add(vB).multiplyScalar(0.5), 'edge', seen)
  pushSnapUnique(out, vB.clone().add(vC).multiplyScalar(0.5), 'edge', seen)
  pushSnapUnique(out, vC.clone().add(vA).multiplyScalar(0.5), 'edge', seen)
  const pt = hit.point
  snapSeg.set(vA, vB)
  snapSeg.closestPointToPoint(pt, true, snapClosest)
  pushSnapUnique(out, snapClosest, 'edge', seen)
  snapSeg.set(vB, vC)
  snapSeg.closestPointToPoint(pt, true, snapClosest)
  pushSnapUnique(out, snapClosest, 'edge', seen)
  snapSeg.set(vC, vA)
  snapSeg.closestPointToPoint(pt, true, snapClosest)
  pushSnapUnique(out, snapClosest, 'edge', seen)
  collectNearbyMeshSnap(mesh, hit, out, seen)
  return out
}

function snapThresholdForKind(kind: SnapCandidate['kind']): number {
  if (kind === 'vertex') return SNAP_SCREEN_THRESHOLD_VERTEX
  if (kind === 'edge') return SNAP_SCREEN_THRESHOLD_EDGE
  if (kind === 'face') return SNAP_SCREEN_THRESHOLD_SURFACE
  return SNAP_SCREEN_THRESHOLD_SURFACE
}

function snapPriority(kind: SnapCandidate['kind']): number {
  if (kind === 'vertex') return 0
  if (kind === 'edge') return 1
  if (kind === 'face') return 2
  return 3
}

/** Привязка к вершине/ребру/грани по близости к курсору на экране. */
function getClosestSnapPoint(
  candidates: SnapCandidate[],
  cam: THREE.Camera,
  mouseNDC: THREE.Vector2,
): THREE.Vector3 | null {
  let best: { point: THREE.Vector3; score: number } | null = null
  for (const c of candidates) {
    snapProj.copy(c.point).project(cam)
    const dx = snapProj.x - mouseNDC.x
    const dy = snapProj.y - mouseNDC.y
    const d = Math.sqrt(dx * dx + dy * dy)
    const th = snapThresholdForKind(c.kind)
    if (d > th) continue
    const score = snapPriority(c.kind) * 100 + d
    if (!best || score < best.score) best = { point: c.point, score }
  }
  return best?.point ?? null
}

function mergeSnapCandidates(base: SnapCandidate[], extra: THREE.Vector3[], kind: SnapCandidate['kind'] = 'surface'): SnapCandidate[] {
  const seen = new Set<string>()
  const out: SnapCandidate[] = []
  for (const c of base) pushSnapUnique(out, c.point, c.kind, seen)
  for (const p of extra) pushSnapUnique(out, p, kind, seen)
  return out
}

const COPLANAR_EPS = 1e-5
const COPLANAR_NORMAL_DOT = 0.999

/** Build one BufferGeometry (world positions) for the coplanar connected face containing the hit triangle. */
function getCoplanarFaceGeometry(mesh: THREE.Mesh, faceIndex: number): THREE.BufferGeometry | null {
  const t0 = performance.now()
  const geom = mesh.geometry
  const pos = geom.attributes.position
  const index = geom.index
  if (!pos) return null
  const numFaces = index ? index.count / 3 : pos.count / 3
  function getFaceVertices(fi: number): [number, number, number] {
    if (index) {
      return [index.getX(fi * 3)!, index.getX(fi * 3 + 1)!, index.getX(fi * 3 + 2)!]
    }
    return [fi * 3, fi * 3 + 1, fi * 3 + 2]
  }
  const edgeToFaces = new Map<string, number[]>()
  function addEdge(na: number, nb: number, faceIdx: number) {
    const key = na < nb ? `${na},${nb}` : `${nb},${na}`
    let arr = edgeToFaces.get(key)
    if (!arr) {
      arr = []
      edgeToFaces.set(key, arr)
    }
    arr.push(faceIdx)
  }
  for (let fi = 0; fi < numFaces; fi++) {
    const [a, b, c] = getFaceVertices(fi)
    addEdge(a, b, fi)
    addEdge(b, c, fi)
    addEdge(c, a, fi)
  }
  const vTemp = new THREE.Vector3()
  const worldPos = (i: number) => {
    vTemp.set(pos.getX(i), pos.getY(i), pos.getZ(i)).applyMatrix4(mesh.matrixWorld)
    return vTemp.clone()
  }
  const getFaceWorldNormal = (fi: number) => {
    const [a, b, c] = getFaceVertices(fi)
    const pa = worldPos(a)
    const pb = worldPos(b)
    const pc = worldPos(c)
    const n = new THREE.Vector3().crossVectors(pb.clone().sub(pa), pc.clone().sub(pa)).normalize()
    return n
  }
  const getFaceCenter = (fi: number) => {
    const [a, b, c] = getFaceVertices(fi)
    return worldPos(a).add(worldPos(b)).add(worldPos(c)).multiplyScalar(1 / 3)
  }
  const hitNormal = getFaceWorldNormal(faceIndex)
  const hitCenter = getFaceCenter(faceIndex).clone()
  const inRegion = new Set<number>([faceIndex])
  const queue = [faceIndex]
  while (queue.length > 0) {
    const fi = queue.shift()!
    const [a, b, c] = getFaceVertices(fi)
    for (const edge of [[a, b], [b, c], [c, a]] as [number, number][]) {
      const key = edge[0] < edge[1] ? `${edge[0]},${edge[1]}` : `${edge[1]},${edge[0]}`
      const neighbors = edgeToFaces.get(key) || []
      for (const n of neighbors) {
        if (inRegion.has(n)) continue
        const nNormal = getFaceWorldNormal(n)
        if (nNormal.dot(hitNormal) < COPLANAR_NORMAL_DOT) continue
        const nCenter = getFaceCenter(n)
        const dist = Math.abs(nCenter.clone().sub(hitCenter).dot(hitNormal))
        if (dist > COPLANAR_EPS) continue
        inRegion.add(n)
        queue.push(n)
      }
    }
  }
  const positions: number[] = []
  inRegion.forEach((fi) => {
    const [a, b, c] = getFaceVertices(fi)
    const p0 = worldPos(a)
    const p1 = worldPos(b)
    const p2 = worldPos(c)
    positions.push(p0.x, p0.y, p0.z, p1.x, p1.y, p1.z, p2.x, p2.y, p2.z)
  })
  if (positions.length === 0) return null
  const outGeom = new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  outGeom.computeVertexNormals()
  const ms = performance.now() - t0
  if (ms > 20) console.log('[getCoplanarFaceGeometry]', ms.toFixed(1), 'ms, numFaces:', numFaces, 'inRegion:', inRegion.size)
  return outGeom
}

function getPointFromHit(hit: THREE.Intersection): THREE.Vector3 {
  const mesh = hit.object as THREE.Mesh
  const face = hit.face!
  const geom = mesh.geometry
  const pos = geom.attributes.position
  if (!pos) return hit.point.clone()
  const vA = new THREE.Vector3(pos.getX(face.a), pos.getY(face.a), pos.getZ(face.a)).applyMatrix4(mesh.matrixWorld)
  const vB = new THREE.Vector3(pos.getX(face.b), pos.getY(face.b), pos.getZ(face.b)).applyMatrix4(mesh.matrixWorld)
  const vC = new THREE.Vector3(pos.getX(face.c), pos.getY(face.c), pos.getZ(face.c)).applyMatrix4(mesh.matrixWorld)
  if (measureSnapMode === 'face') {
    return vA.clone().add(vB).add(vC).multiplyScalar(1 / 3)
  }
  if (measureSnapMode === 'vertex') {
    const dA = hit.point.distanceTo(vA)
    const dB = hit.point.distanceTo(vB)
    const dC = hit.point.distanceTo(vC)
    if (dA <= dB && dA <= dC) return vA
    if (dB <= dC) return vB
    return vC
  }
  if (measureSnapMode === 'edge') {
    const segAB = new THREE.Line3(vA, vB)
    const segBC = new THREE.Line3(vB, vC)
    const segCA = new THREE.Line3(vC, vA)
    const pt = hit.point.clone()
    const closest = new THREE.Vector3()
    let bestDist = Infinity
    let bestPoint = pt.clone()
    segAB.closestPointToPoint(pt, true, closest)
    let d = pt.distanceTo(closest)
    if (d < bestDist) {
      bestDist = d
      bestPoint.copy(closest)
    }
    segBC.closestPointToPoint(pt, true, closest)
    d = pt.distanceTo(closest)
    if (d < bestDist) {
      bestDist = d
      bestPoint.copy(closest)
    }
    segCA.closestPointToPoint(pt, true, closest)
    d = pt.distanceTo(closest)
    if (d < bestDist) bestPoint.copy(closest)
    return bestPoint
  }
  return hit.point.clone()
}

function nextModelId() {
  return `model_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`
}

function renderModelThumbnail(group: THREE.Object3D, width = 160, height = 120): Promise<string> {
  return new Promise((resolve) => {
    if (!renderer) {
      resolve('')
      return
    }
    try {
      const box = new THREE.Box3().setFromObject(group)
      const size = box.getSize(new THREE.Vector3())
      const center = box.getCenter(new THREE.Vector3())
      if (size.x + size.y + size.z < 0.001) {
        resolve('')
        return
      }
      const maxDim = Math.max(size.x, size.y, size.z)
      const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, maxDim * 5)
      camera.position.copy(center).add(new THREE.Vector3(maxDim * 0.8, maxDim * 0.6, maxDim * 0.8))
      camera.lookAt(center)
      const tempScene = new THREE.Scene()
      tempScene.background = new THREE.Color(0xf0f0f0)
      const thumbClone = group.clone(true)
      tempScene.add(thumbClone)
      tempScene.add(new THREE.AmbientLight(0xffffff, 0.8))
      const dir = new THREE.DirectionalLight(0xffffff, 0.6)
      dir.position.set(maxDim, maxDim, maxDim)
      tempScene.add(dir)
      const rt = new THREE.WebGLRenderTarget(width, height, { antialias: true })
      renderer.setRenderTarget(rt)
      renderer.render(tempScene, camera)
      const pixels = new Uint8ClampedArray(width * height * 4)
      renderer.readRenderTargetPixels(rt, 0, 0, width, height, pixels)
      renderer.setRenderTarget(null)
      rt.dispose()
      disposeObject3DResources(thumbClone)
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        resolve('')
        return
      }
      const imageData = ctx.createImageData(width, height)
      for (let y = height - 1; y >= 0; y--) {
        for (let x = 0; x < width; x++) {
          const src = (y * width + x) * 4
          const dst = ((height - 1 - y) * width + x) * 4
          imageData.data[dst] = pixels[src]
          imageData.data[dst + 1] = pixels[src + 1]
          imageData.data[dst + 2] = pixels[src + 2]
          imageData.data[dst + 3] = pixels[src + 3]
        }
      }
      ctx.putImageData(imageData, 0, 0)
      resolve(canvas.toDataURL('image/jpeg', 0.82) || '')
    } catch {
      resolve('')
    }
  })
}

function clearMeshGroup() {
  while (meshGroup.children.length) {
    const child = meshGroup.children[0]
    meshGroup.remove(child)
    if (child instanceof THREE.Mesh) {
      child.geometry?.dispose()
      if (child.material) {
        const m = child.material
        Array.isArray(m) ? m.forEach((mat: THREE.Material) => mat.dispose()) : m.dispose()
      }
    } else {
      child.traverse((obj: THREE.Object3D) => {
        if (obj instanceof THREE.Mesh || obj instanceof THREE.Line) {
          obj.geometry?.dispose()
          if (obj.material) {
            const mat = obj.material
            Array.isArray(mat) ? mat.forEach((m: THREE.Material) => m.dispose()) : mat.dispose()
          }
        }
      })
    }
  }
  overlayGroupByModelId.forEach((_g, id) => removeOverlayForModel(id, true))
  overlaySourceByModelId.clear()
  hiddenOutlineByComponentId.forEach((helper) => {
    hiddenOutlineGroup.remove(helper)
    helper.geometry.dispose()
    ;(helper.material as THREE.Material).dispose()
  })
  hiddenOutlineByComponentId.clear()
  componentTreeByModel.value = {}
  selectedComponentRowId.value = null
  clearComponentHighlight()
}

function loadGlbUrl(
  url: string,
  loadStartedAt?: number,
  opts?: { modelId: string; modelName: string },
  partMeta?: PartColorMeta | null,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const loader = new GLTFLoader()
    loader.load(
      url,
      async (gltf) => {
        const t0 = loadStartedAt ?? performance.now()
        const wrapper = new THREE.Group()
        if (opts) {
          wrapper.userData = { modelId: opts.modelId }
          modelGroupsById.set(opts.modelId, wrapper)
        } else {
          clearMeshGroup()
          modelGroupsById.clear()
          loadedModels.value = []
        }
        wrapper.add(gltf.scene)
        ensureModelUnitsMillimeters(wrapper)
        delete wrapper.userData.explodeCacheReady
        updateModelExplodeProfileOnImport(wrapper, opts?.modelName)
        finalizeModelPartColors(gltf.scene, partMeta)
        const hadModelsBeforeAdd = meshGroup.children.length > 0
        meshGroup.add(wrapper)
        if (opts) buildComponentTreeForModel(opts.modelId, wrapper)
        applyShadingMode()
        syncWireframeEdges(wrapper)
        if (currentSectionAxis) setSectionAxis(currentSectionAxis)
        else if (sectionPlane) applySectionToMeshGroup(sectionPlane)
        const loadBox = new THREE.Box3().setFromObject(wrapper)
        const sceneMs = performance.now() - t0
          if (!loadBox.isEmpty()) {
          const size = loadBox.getSize(new THREE.Vector3())
          console.log(
            `${LOG_PREFIX} GLB: габариты ${size.x.toFixed(1)} x ${size.y.toFixed(1)} x ${size.z.toFixed(1)}, загрузка в сцену: ${(sceneMs / 1000).toFixed(2)} с`
          )
        }
        URL.revokeObjectURL(url)
        if (opts) {
          const visibleCount = loadedModels.value.filter((m) => m.inScene).length
          const inScene = visibleCount < MAX_MODELS_IN_SCENE
          if (!inScene) {
            meshGroup.remove(wrapper)
            if (opts) removeOverlayForModel(opts.modelId)
            wrapper.visible = false
            modelGroupsById.set(opts.modelId, wrapper)
            logger.info('Viewer3D', `Лимит сцены (${MAX_MODELS_IN_SCENE}): модель добавлена в библиотеку`)
          }
          loadedModels.value = [
            ...loadedModels.value,
            { id: opts.modelId, name: opts.modelName, thumbnailDataUrl: THUMBNAIL_PLACEHOLDER, inScene },
          ]
          if (inScene) {
            focusedModelId.value = opts.modelId
            expandedModelIds.value = { ...expandedModelIds.value, [opts.modelId]: true }
            afterModelAddedToScene(wrapper, opts.modelId, hadModelsBeforeAdd, true)
            const sceneBox = new THREE.Box3().setFromObject(meshGroup)
            if (!sceneBox.isEmpty()) {
              if (!hadModelsBeforeAdd) centerModel(sceneBox)
              else if (!placementActive.value) refreshScenePresentationFromReference()
            }
          }
          loadedFileName = opts.modelName
          const scheduleThumb = () => {
            const cb = () => {
              renderModelThumbnail(wrapper).then((thumb) => {
                if (thumb) {
                  const idx = loadedModels.value.findIndex((m) => m.id === opts.modelId)
                  if (idx >= 0) {
                    const next = [...loadedModels.value]
                    next[idx] = { ...next[idx], thumbnailDataUrl: thumb }
                    loadedModels.value = next
                  }
                }
              })
            }
            if (typeof requestIdleCallback !== 'undefined') {
              requestIdleCallback(cb, { timeout: 500 })
            } else {
              setTimeout(cb, 100)
            }
          }
          scheduleThumb()
          if (!inScene) {
            if (meshGroup.children.length > 0) {
              const box = new THREE.Box3().setFromObject(meshGroup)
              centerModel(box)
            }
            alert(`В сцене уже ${MAX_MODELS_IN_SCENE} моделей. Модель добавлена в библиотеку — нажмите на неё, чтобы показать.`)
          }
        } else if (!loadBox.isEmpty()) {
          anchorModelCenterAtWorldOrigin(wrapper)
          centerModel(new THREE.Box3().setFromObject(meshGroup))
        }
        scheduleSceneMetricsRecalc()
        resolve()
      },
      undefined,
      (err) => {
        URL.revokeObjectURL(url)
        reject(err)
      }
    )
  })
}

async function loadSTL(
  arrayBuffer: ArrayBuffer,
  filename: string,
  opts?: { modelId: string; modelName: string },
  partMeta?: PartColorMeta | null,
): Promise<void> {
  console.log(`${LOG_PREFIX} STL: парсинг, размер ${arrayBuffer.byteLength} байт`)
  const loader = new STLLoader()
  const geometry = loader.parse(arrayBuffer)
  console.log(`${LOG_PREFIX} STL: вершин ${geometry.attributes.position?.count ?? 0}, добавление в сцену`)
  geometry.computeVertexNormals()
  const material = new THREE.MeshPhongMaterial({
    color: DEFAULT_COLOR,
    specular: DEFAULT_SPECULAR,
    shininess: 30,
    flatShading: false,
  })
  const mesh = new THREE.Mesh(geometry, material)
  mesh.name = (filename || 'model').replace(/\.[^.]+$/, '') || 'model'
  const wrapper = new THREE.Group()
  if (opts) {
    wrapper.userData = { modelId: opts.modelId }
    modelGroupsById.set(opts.modelId, wrapper)
  } else {
    clearMeshGroup()
    modelGroupsById.clear()
    loadedModels.value = []
  }
  wrapper.add(mesh)
  const splitCount = splitStlMergedMeshes(wrapper, partMeta)
  if (partMeta) assignPartMetaToStlMeshes(wrapper, partMeta)
  finalizeModelPartColors(wrapper, partMeta)
  if (splitCount <= 1 && !partMeta) {
    logger.info(
      'Viewer3D',
      'STL: одно связное тело — дерево из одной детали; для сборки и цветов лучше STEP или GLB',
    )
  }
  applyShadingMode()
  const hadModelsBeforeAddStl = meshGroup.children.length > 0
  meshGroup.add(wrapper)
  // ensureExplodeCacheForModel(wrapper)
  if (opts) buildComponentTreeForModel(opts.modelId, wrapper)
  syncWireframeEdges(wrapper)
  if (currentSectionAxis) setSectionAxis(currentSectionAxis)
  else if (sectionPlane) applySectionToMeshGroup(sectionPlane)
  if (opts) {
    const visibleCount = loadedModels.value.filter((m) => m.inScene).length
    const inScene = visibleCount < MAX_MODELS_IN_SCENE
    if (!inScene) {
      meshGroup.remove(wrapper)
      if (opts) removeOverlayForModel(opts.modelId)
      wrapper.visible = false
      modelGroupsById.set(opts.modelId, wrapper)
      logger.info('Viewer3D', `Лимит сцены (${MAX_MODELS_IN_SCENE}): модель добавлена в библиотеку`)
    }
    loadedModels.value = [
      ...loadedModels.value,
      { id: opts.modelId, name: opts.modelName, thumbnailDataUrl: THUMBNAIL_PLACEHOLDER, inScene },
    ]
    loadedFileName = opts.modelName
    if (inScene) {
      afterModelAddedToScene(wrapper, opts.modelId, hadModelsBeforeAddStl, true)
      const bbox = new THREE.Box3().setFromObject(meshGroup)
      if (!bbox.isEmpty()) {
        if (!hadModelsBeforeAddStl) centerModel(bbox)
        else if (!placementActive.value) refreshScenePresentationFromReference()
      }
    }
    const scheduleThumb = () => {
      const cb = () => {
        renderModelThumbnail(wrapper).then((thumb) => {
          if (thumb) {
            const idx = loadedModels.value.findIndex((m) => m.id === opts.modelId)
            if (idx >= 0) {
              const next = [...loadedModels.value]
              next[idx] = { ...next[idx], thumbnailDataUrl: thumb }
              loadedModels.value = next
            }
          }
        })
      }
      if (typeof requestIdleCallback !== 'undefined') {
        requestIdleCallback(cb, { timeout: 500 })
      } else {
        setTimeout(cb, 100)
      }
    }
    scheduleThumb()
    if (!inScene) alert(`В сцене уже ${MAX_MODELS_IN_SCENE} моделей. Модель добавлена в библиотеку — нажмите на неё, чтобы показать.`)
  } else {
    const box = new THREE.Box3().setFromObject(meshGroup)
    if (!box.isEmpty()) centerModel(box)
  }
  scheduleSceneMetricsRecalc()
}

const LOG_PREFIX = '[Viewer3D]'

/** Лимит размера файла для STEP/IGES (байты). 30 МБ. */
const STEP_IGES_MAX_FILE_BYTES = 30 * 1024 * 1024

/** Таймаут серверной конвертации STEP->GLB (мс). */
const STEP_SERVER_CONVERT_TIMEOUT_MS = 45_000
/** Таймаут запроса метаданных STEP (мс). */
const STEP_METADATA_TIMEOUT_MS = 20_000
/** Таймаут fallback-конвертации STEP/IGES в браузере (мс). */
const STEP_WASM_CONVERT_TIMEOUT_MS = 90_000

/** Для STEP: сначала пробуем конвертацию на сервере; при 501/500/413 — fallback на WASM. */
function fetchWithTimeout(input: RequestInfo | URL, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs)
  return fetch(input, { ...init, signal: controller.signal }).finally(() => window.clearTimeout(timeoutId))
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timeoutId = window.setTimeout(() => reject(new Error(message)), timeoutMs)
    promise
      .then((value) => resolve(value))
      .catch((err) => reject(err))
      .finally(() => window.clearTimeout(timeoutId))
  })
}

function handleFile(file: File, metaByBaseName?: Map<string, PartColorMeta>): Promise<void> {
  return new Promise((resolve, reject) => {
    const ext = (file.name.split('.').pop() || '').toLowerCase()
    const baseName = file.name.replace(/\.[^.]+$/, '').toLowerCase()
    let partMeta: PartColorMeta | null = metaByBaseName?.get(baseName) ?? null
    logger.info('Viewer3D', `Загрузка модели: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`)
    console.groupCollapsed(`${LOG_PREFIX} Загрузка файла: ${file.name}`)
    console.log('имя:', file.name)
    console.log('расширение:', ext)
    console.log('размер (байт):', file.size)
    console.log('тип MIME:', file.type || '(не задан)')
    const modelId = nextModelId()
    const opts = { modelId, modelName: file.name }
    const reader = new FileReader()
    reader.onload = async () => {
      const buf = reader.result as ArrayBuffer
      if (!partMeta) {
        partMeta = await tryLoadPartMetaByBaseName(baseName)
      }
      if (!partMeta && ['step', 'stp', 'igs', 'iges', 'stl'].includes(ext)) {
        partMeta = await tryLoadKompasMetaAuto(file.name)
      }
      if (!partMeta) {
        logger.info(
          'Viewer3D',
          `meta.json не найден для "${baseName}" (STL: авто-раскраска сегментов; STEP/GLB: цвета из файла)`,
        )
      }
    console.log('ArrayBuffer (байт):', buf?.byteLength ?? 0)
    if (ext === 'stl') {
      console.log('формат: STL — загрузка через STLLoader')
      console.groupEnd()
      await loadSTL(buf, file.name, opts, partMeta)
      resolve()
      return
    }
    if (['step', 'stp', 'igs', 'iges'].includes(ext)) {
      console.log(`формат: ${ext.toUpperCase()} — загрузка через opencascade.js или сервер`)
      console.groupEnd()
      if (file.size > STEP_IGES_MAX_FILE_BYTES) {
        const mb = (STEP_IGES_MAX_FILE_BYTES / (1024 * 1024)).toFixed(0)
        logger.warn('Viewer3D', `Файл больше ${mb} МБ. Лимит загрузки: ${mb} МБ.`)
        resolve()
        return
      }
      isLoading.value = true
      const t0 = performance.now()
      try {
        let glbUrl: string
        if (ext === 'step' || ext === 'stp') {
          try {
            const fdConvert = new FormData()
            fdConvert.append('file', file, file.name)
            const res = await fetchWithTimeout(
              '/api/convert/step-to-glb',
              { method: 'POST', body: fdConvert },
              STEP_SERVER_CONVERT_TIMEOUT_MS
            )
            if (res.ok) {
              const blob = await res.blob()
              glbUrl = URL.createObjectURL(blob)
              console.log(`${LOG_PREFIX} конвертация на сервере`)
            } else {
              if (res.status === 413) logger.warn('Viewer3D', 'Файл слишком большой для сервера (лимит 100 МБ)')
              glbUrl = await withTimeout(
                loadStepOrIgesToGlbUrl(buf, ext),
                STEP_WASM_CONVERT_TIMEOUT_MS,
                'Превышено время браузерной конвертации STEP/IGES'
              )
            }
          } catch (e) {
            console.warn(`${LOG_PREFIX} серверная конвертация недоступна, используем WASM:`, e)
            glbUrl = await withTimeout(
              loadStepOrIgesToGlbUrl(buf, ext),
              STEP_WASM_CONVERT_TIMEOUT_MS,
              'Превышено время браузерной конвертации STEP/IGES'
            )
          }
        } else {
          glbUrl = await withTimeout(
            loadStepOrIgesToGlbUrl(buf, ext),
            STEP_WASM_CONVERT_TIMEOUT_MS,
            'Превышено время браузерной конвертации STEP/IGES'
          )
        }
        await loadGlbUrl(glbUrl, performance.now(), opts, partMeta)
        const totalMs = performance.now() - t0
        logger.info('Viewer3D', `Модель загружена: ${file.name} за ${(totalMs / 1000).toFixed(2)} с`)
        console.log(`${LOG_PREFIX} Модель загружена. Всего: ${(totalMs / 1000).toFixed(2)} с`)
        resolve()
      } catch (err) {
        logger.error('Viewer3D', `Ошибка загрузки STEP/IGES: ${file.name}`, err)
        console.error(`${LOG_PREFIX} Ошибка загрузки STEP/IGES:`, err)
        if (err instanceof Error) console.error(`${LOG_PREFIX} message:`, err.message, 'stack:', err.stack)
        alert(`Не удалось загрузить ${file.name}. ${err instanceof Error ? err.message : 'Проверьте сервер и формат файла.'}`)
        reject(err)
      } finally {
        isLoading.value = false
      }
      return
    }
    if (['glb', 'gltf'].includes(ext)) {
      console.log('формат: GLB/GLTF — загрузка через GLTFLoader')
      console.groupEnd()
      const url = URL.createObjectURL(file)
      try {
        await loadGlbUrl(url, performance.now(), opts, partMeta)
      } finally {
        URL.revokeObjectURL(url)
      }
      resolve()
      return
    }
    if (ext === 'jt') {
      console.log('формат: JT — отправка на конвертер')
      console.groupEnd()
      isLoading.value = true
      const baseUrl = (import.meta as any).env?.VITE_CONVERTER_URL ?? ''
      const converterBase = baseUrl ? baseUrl.replace(/\/$/, '') : ''
      const useProxy = import.meta.env.DEV && !converterBase
      const convertUrl = useProxy ? '/api/convert/jt' : (converterBase ? `${converterBase}/convert/jt` : '')
      if (!convertUrl) {
        console.error(`${LOG_PREFIX} VITE_CONVERTER_URL не задан`)
        isLoading.value = false
        alert('Конвертер JT не настроен (VITE_CONVERTER_URL)')
        resolve()
        return
      }
      const formData = new FormData()
      formData.append('file', file)
      fetch(convertUrl, {
        method: 'POST',
        body: formData,
      })
        .then(async (res) => {
          console.log(`${LOG_PREFIX} JT fetch response ok:`, res.ok, res.status)
          if (!res.ok) {
            let text = ''
            try {
              text = await res.text()
            } catch {
              // some converter backends close body stream on 5xx
            }
            let msg = `${res.status} ${res.statusText}`.trim()
            if (text) {
              try {
                const body = JSON.parse(text)
                msg = body.detail ? `${body.error || ''}: ${body.detail}` : (body.error || msg)
              } catch (_) {
                msg = text.slice(0, 300)
              }
            } else if (res.status >= 500) {
              msg = `${msg}. Сервис JT-конвертации недоступен или упал на обработке файла.`
            }
            throw new Error(msg)
          }
          return res.blob()
        })
        .then((blob) => {
          console.log(`${LOG_PREFIX} JT blob size:`, blob.size, blob.type)
          const url = URL.createObjectURL(blob)
          return loadGlbUrl(url, performance.now(), undefined, null)
        })
        .then(() => {
          console.log(`${LOG_PREFIX} JT loadGlbUrl done`)
          loadedFileName = file.name
        })
        .catch((err) => {
          console.error(`${LOG_PREFIX} Ошибка конвертации JT:`, err)
          alert('Ошибка конвертации JT: ' + (err instanceof Error ? err.message : String(err)))
        })
        .then(() => resolve())
        .catch((e) => {
          reject(e)
        })
        .finally(() => {
          console.log(`${LOG_PREFIX} JT finally, loading=false`)
          isLoading.value = false
        })
      return
    }
    console.warn('формат: неизвестный или не поддерживается, расширение:', ext)
    console.groupEnd()
    alert('Формат не поддерживается')
    resolve()
  }
  reader.onerror = () => {
    console.error(`${LOG_PREFIX} Ошибка чтения файла:`, file.name, reader.error)
    console.groupEnd()
    reject(reader.error)
  }
  reader.readAsArrayBuffer(file)
  })
}

function openFileDialog() {
  if (!fileInput) {
    fileInput = document.createElement('input')
    fileInput.type = 'file'
    fileInput.accept = '.stl,.step,.stp,.igs,.iges,.glb,.gltf'
    fileInput.multiple = true
    fileInput.onchange = async () => {
      const files = fileInput?.files
      if (files?.length) {
        const arr = Array.from(files)
        const metaByBaseName = new Map<string, PartColorMeta>()
        for (const f of arr) {
          if (!f.name.toLowerCase().endsWith('.json')) continue
          const baseName = f.name.replace(/\.meta\.json$/i, '').replace(/\.json$/i, '').toLowerCase()
          try {
            const parsed = parsePartColorMeta(JSON.parse(await f.text()))
            if (parsed) metaByBaseName.set(baseName, parsed)
          } catch {
            logger.warn('Viewer3D', `Файл ${f.name} пропущен: это невалидный meta.json`)
          }
        }
        if (arr.length > MAX_FILES_SELECT) {
          logger.warn('Viewer3D', `Выбрано ${arr.length} файлов, загружаем первые ${MAX_FILES_SELECT}`)
          alert(`Выбрано ${arr.length} файлов. Загружаем первые ${MAX_FILES_SELECT} для стабильной работы.`)
        }
        const toLoad = arr.filter((f) => !f.name.toLowerCase().endsWith('.json')).slice(0, MAX_FILES_SELECT)
        for (const file of toLoad) {
          try {
            await handleFile(file, metaByBaseName)
          } catch (e) {
            logger.error('Viewer3D', `Ошибка загрузки ${file.name}`, e)
          }
        }
      }
      if (fileInput) fileInput.value = ''
    }
  }
  fileInput.click()
}

function takeScreenshot(): Promise<string> {
  return new Promise((resolve) => {
    if (!renderer || !scene || !camera || !containerRef.value) {
      resolve('')
      return
    }
    const container = containerRef.value
    const width = Math.max(1, container.clientWidth)
    const height = Math.max(1, container.clientHeight)
    const prevPixelRatio = renderer.getPixelRatio()
    const prevSize = new THREE.Vector2()
    renderer.getSize(prevSize)
    const prevAspect = camera.aspect

    const shotRatio = screenshotPixelRatio()
    try {
      renderer.setPixelRatio(shotRatio)
      renderer.setSize(width, height, false)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      renderer.render(scene, camera)

      const labelEls = [
        measurementLabelEl,
        measurementLabelEl0,
        measurementLabelEl1,
        measurementLabelEl2,
        measurementPerpLabelEl,
        measurementExtraLabelEl,
        diameterSecondLabelEl,
      ].filter(Boolean) as HTMLDivElement[]
      const hasVisibleLabels = labelEls.some(
        (el) => el.style.display !== 'none' && (el.textContent || '').trim(),
      )
      if (!hasVisibleLabels) {
        resolve(renderer.domElement.toDataURL('image/png'))
        return
      }
      const canvas = document.createElement('canvas')
      canvas.width = renderer.domElement.width
      canvas.height = renderer.domElement.height
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        resolve(renderer.domElement.toDataURL('image/png'))
        return
      }
      ctx.drawImage(renderer.domElement, 0, 0)
      const canvasRect = renderer.domElement.getBoundingClientRect()
      const scaleX = canvas.width / Math.max(canvasRect.width, 1)
      const scaleY = canvas.height / Math.max(canvasRect.height, 1)
      for (const el of labelEls) {
        if (el.style.display === 'none') continue
        const text = (el.textContent || '').trim()
        if (!text) continue
        const r = el.getBoundingClientRect()
        const x = (r.left - canvasRect.left) * scaleX
        const y = (r.top - canvasRect.top) * scaleY
        const style = getComputedStyle(el)
        const fontSize = parseFloat(style.fontSize) || 14
        ctx.font = style.font.replace(
          /(\d+(?:\.\d+)?)px/,
          `${Math.round(fontSize * scaleY)}px`,
        )
        ctx.fillStyle = style.color
        ctx.textBaseline = 'top'
        const padding = 2 * scaleY
        const bg = style.backgroundColor
        if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
          const m = ctx.measureText(text)
          ctx.fillStyle = bg
          ctx.fillRect(x - padding, y - padding, m.width + padding * 2, fontSize * scaleY + padding * 2)
          ctx.fillStyle = style.color
        }
        ctx.fillText(text, x, y)
      }
      resolve(canvas.toDataURL('image/png'))
    } finally {
      renderer.setPixelRatio(prevPixelRatio)
      renderer.setSize(prevSize.x, prevSize.y, false)
      camera.aspect = prevAspect
      camera.updateProjectionMatrix()
      renderer.render(scene, camera)
      controls?.handleResize()
    }
  })
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function exportGlb(): Promise<void> {
  if (!meshGroup || meshGroup.children.length === 0) {
    logger.warn('Viewer3D', 'Экспорт GLB: модель не загружена')
    alert('Загрузите 3D модель')
    return Promise.resolve()
  }
  const name = (loadedFileName ?? 'model').replace(/\.[^.]+$/, '') || 'model'
  logger.info('Viewer3D', `Экспорт GLB: ${name}.glb`)
  const exporter = new GLTFExporter()
  return exporter
    .parseAsync(meshGroup, { binary: true })
    .then((arrayBuffer) => {
      downloadBlob(new Blob([arrayBuffer as ArrayBuffer], { type: 'model/gltf-binary' }), `${name}.glb`)
      logger.info('Viewer3D', `Экспорт GLB готов: ${name}.glb`)
    })
    .catch((err) => {
      logger.error('Viewer3D', 'Ошибка экспорта GLB', err)
      console.error(`${LOG_PREFIX} exportGlb:`, err)
      alert('Ошибка экспорта GLB')
    })
}

function exportStl(): void {
  if (!meshGroup || meshGroup.children.length === 0) {
    logger.warn('Viewer3D', 'Экспорт STL: модель не загружена')
    alert('Загрузите 3D модель')
    return
  }
  const name = (loadedFileName ?? 'model').replace(/\.[^.]+$/, '') || 'model'
  logger.info('Viewer3D', `Экспорт STL: ${name}.stl`)
  const exporter = new STLExporter()
  const data = exporter.parse(meshGroup, { binary: true }) as ArrayBuffer
  downloadBlob(new Blob([data], { type: 'application/octet-stream' }), `${name}.stl`)
  logger.info('Viewer3D', `Экспорт STL готов: ${name}.stl`)
}

onMounted(() => {
  initScene()
  document.addEventListener('mousedown', onOrientationClickOutside)
  document.addEventListener('mousedown', onMouseSettingsClickOutside)
  document.addEventListener('mousedown', onGlobalMouseDown)
  window.addEventListener('keydown', onWindowKeyDown)
  getOpenCascade().then(() => {
    console.log(`${LOG_PREFIX} WASM предзагружен (первый STEP/IGES откроется быстрее)`)
  })
})

onUnmounted(() => {
  document.removeEventListener('mousedown', onOrientationClickOutside)
  document.removeEventListener('mousedown', onMouseSettingsClickOutside)
  document.removeEventListener('mousedown', onGlobalMouseDown)
  window.removeEventListener('keydown', onWindowKeyDown)
  window.removeEventListener('resize', onResize)
  detachBoxSelectWindowListeners()
  if (containerRef.value) {
    containerRef.value.removeEventListener('mousemove', onContainerMouseMove, false)
  }
  if (renderer?.domElement) {
    renderer.domElement.removeEventListener('click', onCanvasClick)
    renderer.domElement.removeEventListener('pointerdown', onCanvasPointerDownCapture, true)
    renderer.domElement.removeEventListener('mousedown', onCanvasMouseDown, true)
    renderer.domElement.removeEventListener('contextmenu', onCanvasContextMenu)
    renderer.domElement.removeEventListener('mousemove', onCanvasMouseMove, false)
    renderer.domElement.removeEventListener('mousemove', onCanvasMouseMovePan, true)
    renderer.domElement.removeEventListener('mouseup', onCanvasMouseUp, true)
    window.removeEventListener('mouseup', onCanvasMouseUp, true)
    renderer.domElement.removeEventListener('wheel', onCanvasWheel)
  }
  controls?.removeEventListener('start', onControlsStart)
  controls?.removeEventListener('end', onControlsEnd)
  while (highlightGroup?.children.length) {
    const c = highlightGroup.children[0]
    highlightGroup.remove(c)
    if ('geometry' in c && c.geometry) c.geometry.dispose()
    if ('material' in c && c.material) (c.material as THREE.Material).dispose()
  }
  clearSavedMeasurementVisuals()
  clearSavedMeasurementLabelElements()
  if (savedMeasurementsGroup && scene) {
    scene.remove(savedMeasurementsGroup)
  }
  if (sectionPlaneMesh) {
    scene.remove(sectionPlaneMesh)
    sectionPlaneMesh.geometry.dispose()
    ;(sectionPlaneMesh.material as THREE.Material).dispose()
    sectionPlaneMesh = null
  }
  if (groundGrid) {
    scene.remove(groundGrid)
    groundGrid.geometry.dispose()
    const gm = groundGrid.material
    if (Array.isArray(gm)) gm.forEach((m) => m.dispose())
    else gm.dispose()
    groundGrid = null
  }
  if (measurementLabelEl && containerRef.value?.contains(measurementLabelEl)) {
    containerRef.value.removeChild(measurementLabelEl)
  }
  measurementLabelEl = null
  for (const el of [measurementLabelEl0, measurementLabelEl1, measurementLabelEl2]) {
    if (el && containerRef.value?.contains(el)) containerRef.value.removeChild(el)
  }
  measurementLabelEl0 = null
  measurementLabelEl1 = null
  measurementLabelEl2 = null
  if (measurementPerpLabelEl && containerRef.value?.contains(measurementPerpLabelEl)) {
    containerRef.value.removeChild(measurementPerpLabelEl)
  }
  measurementPerpLabelEl = null
  if (measurementExtraLabelEl && containerRef.value?.contains(measurementExtraLabelEl)) {
    containerRef.value.removeChild(measurementExtraLabelEl)
  }
  measurementExtraLabelEl = null
  if (diameterSecondLabelEl && containerRef.value?.contains(diameterSecondLabelEl)) {
    containerRef.value.removeChild(diameterSecondLabelEl)
  }
  diameterSecondLabelEl = null
  if (hoverTooltipEl && containerRef.value?.contains(hoverTooltipEl)) {
    containerRef.value.removeChild(hoverTooltipEl)
  }
  hoverTooltipEl = null
  disposeAllLoadedModels()
  if (animationId) cancelAnimationFrame(animationId)
  stripStaleAssemblyFaceTriangles()
  disposeAssemblyHighlightGroupMeshes()
  if (assemblyHighlightGroup && scene) {
    scene.remove(assemblyHighlightGroup)
    assemblyHighlightGroup = undefined
  }
  controls?.dispose()
  renderer?.dispose()
  if (containerRef.value && renderer?.domElement) {
    containerRef.value.removeChild(renderer.domElement)
  }
})

function loadModelFile(file: File): Promise<void> {
  return handleFile(file)
}

function getMeasurementReport(): { length: number; dx: number; dy: number; dz: number } | null {
  if (measurementPoints.length !== 2) return null
  const p0 = measurementPoints[0]
  const p1 = measurementPoints[1]
  return {
    length: p0.distanceTo(p1),
    dx: p1.x - p0.x,
    dy: p1.y - p0.y,
    dz: p1.z - p0.z,
  }
}

function onModelCardClick(item: { id: string; inScene: boolean }) {
  onModelTreeHeaderClick(item)
}

function setModelInScene(id: string, inScene: boolean) {
  const group = modelGroupsById.get(id)
  const item = loadedModels.value.find((m) => m.id === id)
  if (!group || !item) return
  if (!inScene && placementModelId.value === id) {
    placementActive.value = false
    placementModelId.value = null
    placementStatusHint.value = ''
    placementCancelRemovesFromScene = false
  }
  if (inScene) {
    const visibleCount = loadedModels.value.filter((m) => m.inScene).length
    if (visibleCount >= MAX_MODELS_IN_SCENE) {
      alert(`В сцене уже ${MAX_MODELS_IN_SCENE} моделей. Уберите модель из сцены, чтобы добавить другую.`)
      return
    }
    if (!meshGroup.children.includes(group)) {
      meshGroup.add(group)
      if (!componentTreeByModel.value[id]) buildComponentTreeForModel(id, group)
    }
    syncWireframeEdges(group)
    applyShadingMode()
    group.visible = true
  } else {
    meshGroup.remove(group)
    removeOverlayForModel(id)
    purgeModelAuxiliaryState(group)
    group.visible = false
  }
  refreshComponentTreeVisibility(id)
  loadedModels.value = loadedModels.value.map((m) => (m.id === id ? { ...m, inScene } : m))
  if (inScene) {
    focusedModelId.value = id
    const othersInScene = loadedModels.value.filter((m) => m.inScene && m.id !== id).length
    if (othersInScene === 0) {
      anchorModelCenterAtWorldOrigin(group)
      const box = new THREE.Box3().setFromObject(meshGroup)
      if (!box.isEmpty()) centerModel(box)
    } else {
      beginModelPlacement(id, { removeFromSceneOnCancel: true })
    }
  } else if (meshGroup.children.length > 0) {
    refreshScenePresentationFromReference()
    applyNavigationForFocusedModel()
  }
  scheduleSceneMetricsRecalc()
}

function deleteFocusedModel() {
  const id = focusedModelId.value
  if (!id || !modelGroupsById.has(id)) return
  if (!window.confirm('Удалить выбранную модель из проекта? Связи сборки и измерения по ней будут очищены.')) return
  focusedModelId.value = null
  removeModel(id)
}

function removeModel(id: string) {
  if (placementModelId.value === id) cancelModelPlacement()
  if (partTreeIsolateState.value?.modelId === id) restorePartTreeIsolate()
  const group = modelGroupsById.get(id)
  if (!group) return
  purgeModelAuxiliaryState(group)
  const nextPin = { ...pinnedByModelId.value }
  delete nextPin[id]
  pinnedByModelId.value = nextPin
  if (focusedModelId.value === id) focusedModelId.value = null
  if (meshGroup) meshGroup.remove(group)
  removeOverlayForModel(id, true)
  const { [id]: _removed, ...restTrees } = componentTreeByModel.value
  componentTreeByModel.value = restTrees
  for (const [key, helper] of hiddenOutlineByComponentId.entries()) {
    if (!key.startsWith(`${id}:`)) continue
    hiddenOutlineGroup.remove(helper)
    helper.geometry.dispose()
    ;(helper.material as THREE.Material).dispose()
    hiddenOutlineByComponentId.delete(key)
  }
  if (selectedComponentRowId.value?.startsWith(`${id}:`)) selectedComponentRowId.value = null
  clearComponentHighlight()
  group.traverse((obj: THREE.Object3D) => {
    if (obj instanceof THREE.Mesh || obj instanceof THREE.Line) {
      obj.geometry?.dispose()
      if (obj.material) {
        const m = obj.material
        Array.isArray(m) ? m.forEach((mat: THREE.Material) => mat.dispose()) : m.dispose()
      }
    }
  })
  modelGroupsById.delete(id)
  loadedModels.value = loadedModels.value.filter((m) => m.id !== id)
  assemblyMates.value = assemblyMates.value.filter(
    (m) => m.sourceId !== id && m.targetId !== id,
  )
  measurementHistory.value = measurementHistory.value.filter((m) => {
    if (m.modelId1 === id || m.modelId2 === id) return false
    if (m.centerModelId === id || m.secondCenterModelId === id) return false
    if (m.arcModelId === id) return false
    if (m.outputPlaneModelId === id) return false
    return true
  })
  if (selectedAssemblyMateId.value && !assemblyMates.value.some((m) => m.id === selectedAssemblyMateId.value)) {
    selectedAssemblyMateId.value = null
  }
  if (selectedMeasurementId.value && !measurementHistory.value.some((m) => m.id === selectedMeasurementId.value)) {
    selectedMeasurementId.value = null
    clearMeasurements()
  } else {
    refreshSelectedMeasurementAfterTransform()
  }
  rebuildSavedMeasurementsVisuals()
  refreshAllAssemblyVisuals()
  loadedFileName = loadedModels.value.length > 0 ? loadedModels.value[loadedModels.value.length - 1].name : null
  if (meshGroup.children.length > 0) {
    const box = new THREE.Box3().setFromObject(meshGroup)
    centerModel(box)
  }
  scheduleSceneMetricsRecalc()
}

function resizeViewport() {
  onResize()
}

function storedPlaneFromExported(p: ExportedAssemblyPlane, modelId: string): StoredAssemblyPlane {
  return {
    modelId,
    localPoint: { x: p.localPoint.x, y: p.localPoint.y, z: p.localPoint.z },
    normal: { x: p.normal.x, y: p.normal.y, z: p.normal.z },
  }
}

function planeToExported(sp: StoredAssemblyPlane, idToName: Map<string, string>): ExportedAssemblyPlane | null {
  const modelName = idToName.get(sp.modelId)
  if (!modelName) return null
  return {
    modelName,
    localPoint: { ...sp.localPoint },
    normal: { ...sp.normal },
  }
}

function mateToExported(m: StoredAssemblyMate, idToName: Map<string, string>): ExportedAssemblyMate | null {
  const sn = idToName.get(m.sourceId)
  if (!sn) return null
  if (m.type === 'coord') {
    const a = planeToExported(m.sourcePlane, idToName)
    if (!a) return null
    return {
      id: m.id,
      type: 'coord',
      sourceModelName: sn,
      sourcePlane: a,
      worldPlane: m.worldPlane,
      distanceMm: m.distanceMm,
      flipNormal: m.flipNormal,
    }
  }
  const tn = idToName.get(m.targetId)
  if (!tn) return null
  if (m.type === 'plane') {
    const a = planeToExported(m.sourcePlane, idToName)
    const b = planeToExported(m.targetPlane, idToName)
    if (!a || !b) return null
    return { id: m.id, type: 'plane', sourceModelName: sn, targetModelName: tn, sourcePlane: a, targetPlane: b }
  }
  if (m.type === 'distance') {
    const a = planeToExported(m.sourcePlane, idToName)
    const b = planeToExported(m.targetPlane, idToName)
    if (!a || !b) return null
    return {
      id: m.id,
      type: 'distance',
      sourceModelName: sn,
      targetModelName: tn,
      sourcePlane: a,
      targetPlane: b,
      distanceMm: m.distanceMm,
    }
  }
  const b1 = planeToExported(m.base1, idToName)
  const b2 = planeToExported(m.base2, idToName)
  const p1 = planeToExported(m.part1, idToName)
  const p2 = planeToExported(m.part2, idToName)
  if (!b1 || !b2 || !p1 || !p2) return null
  return {
    id: m.id,
    type: 'symmetric',
    sourceModelName: sn,
    targetModelName: tn,
    base1: b1,
    base2: b2,
    part1: p1,
    part2: p2,
  }
}

function mateFromExported(m: ExportedAssemblyMate, nameToId: Map<string, string>): StoredAssemblyMate | null {
  const sid = nameToId.get(m.sourceModelName)
  if (!sid) return null
  const ip = (p: ExportedAssemblyPlane): StoredAssemblyPlane | null => {
    const mid = nameToId.get(p.modelName)
    if (!mid) return null
    return storedPlaneFromExported(p, mid)
  }
  if (m.type === 'coord') {
    const sp = ip(m.sourcePlane)
    if (!sp) return null
    return {
      id: m.id,
      type: 'coord',
      sourceId: sid,
      sourcePlane: sp,
      worldPlane: m.worldPlane,
      distanceMm: m.distanceMm,
      flipNormal: !!m.flipNormal,
    }
  }
  const tid = nameToId.get(m.targetModelName)
  if (!tid) return null
  if (m.type === 'plane') {
    const sp = ip(m.sourcePlane)
    const tp = ip(m.targetPlane)
    if (!sp || !tp) return null
    return { id: m.id, type: 'plane', sourceId: sid, targetId: tid, sourcePlane: sp, targetPlane: tp }
  }
  if (m.type === 'distance') {
    const sp = ip(m.sourcePlane)
    const tp = ip(m.targetPlane)
    if (!sp || !tp) return null
    return {
      id: m.id,
      type: 'distance',
      sourceId: sid,
      targetId: tid,
      sourcePlane: sp,
      targetPlane: tp,
      distanceMm: m.distanceMm,
    }
  }
  const b1 = ip(m.base1)
  const b2 = ip(m.base2)
  const p1 = ip(m.part1)
  const p2 = ip(m.part2)
  if (!b1 || !b2 || !p1 || !p2) return null
  return {
    id: m.id,
    type: 'symmetric',
    sourceId: sid,
    targetId: tid,
    base1: b1,
    base2: b2,
    part1: p1,
    part2: p2,
  }
}

function collectPartLayersForProject(): AssemblyProjectPartLayerV1[] {
  const out: AssemblyProjectPartLayerV1[] = []
  const seen = new Set<string>()
  for (const m of loadedModels.value) {
    const g = modelGroupsById.get(m.id)
    if (!g) continue
    g.traverse((obj: THREE.Object3D) => {
      if (!(obj instanceof THREE.Mesh)) return
      const geomKey = meshPartGroupKey(obj, inferComponentLabel(obj) || obj.name || '')
      const layerId = meshLayerByUuid.value[obj.uuid] ?? 'layer-0'
      const colorOverride = layerColorOverrideByUuid.value[obj.uuid]
      if (layerId === 'layer-0' && !colorOverride) return
      const dedupe = `${m.name}\0${geomKey}\0${layerId}\0${colorOverride ?? ''}`
      if (seen.has(dedupe)) return
      seen.add(dedupe)
      out.push({
        modelName: m.name,
        geomKey,
        layerId,
        ...(colorOverride ? { colorOverride } : {}),
      })
    })
  }
  return out
}

function applyPartLayersFromProject(partLayers: AssemblyProjectPartLayerV1[]) {
  if (!partLayers.length) return
  const nameToId = new Map(loadedModels.value.map((m) => [m.name, m.id]))
  const nextMeshLayer: Record<string, string> = { ...meshLayerByUuid.value }
  const nextColors: Record<string, string> = { ...layerColorOverrideByUuid.value }
  for (const pl of partLayers) {
    const modelId = nameToId.get(pl.modelName)
    const g = modelId ? modelGroupsById.get(modelId) : undefined
    if (!g) continue
    g.traverse((obj: THREE.Object3D) => {
      if (!(obj instanceof THREE.Mesh)) return
      if (meshGeometryGroupKey(obj) !== pl.geomKey) return
      nextMeshLayer[obj.uuid] = pl.layerId
      if (pl.colorOverride) {
        nextColors[obj.uuid] = pl.colorOverride
        if (obj.material && 'color' in obj.material) {
          ;(obj.material as THREE.MeshPhongMaterial).color.set(pl.colorOverride)
        }
      }
    })
  }
  meshLayerByUuid.value = nextMeshLayer
  layerColorOverrideByUuid.value = nextColors
  applySceneLayerVisibility()
}

function saveAssemblyProjectJson(): void {
  if (loadedModels.value.length === 0) {
    alert('Нет загруженных моделей — нечего сохранять.')
    return
  }
  const idToName = new Map(loadedModels.value.map((m) => [m.id, m.name]))
  const models = loadedModels.value.map((m) => {
    const g = modelGroupsById.get(m.id)
    const s = g ? getTransformSnapshot(g) : null
    return {
      modelName: m.name,
      inScene: m.inScene,
      px: s?.px ?? 0,
      py: s?.py ?? 0,
      pz: s?.pz ?? 0,
      rx: s?.rx ?? 0,
      ry: s?.ry ?? 0,
      rz: s?.rz ?? 0,
    }
  })
  const assemblyMatesOut: ExportedAssemblyMate[] = []
  for (const m of assemblyMates.value) {
    const ex = mateToExported(m, idToName)
    if (ex) assemblyMatesOut.push(ex)
  }
  const partLayers = collectPartLayersForProject()
  const payload: AssemblyProjectFileV1 = {
    format: '3d-viewer-assembly-project',
    version: 1,
    savedAt: new Date().toISOString(),
    models,
    assemblyMates: assemblyMatesOut,
    sceneLayers: sceneLayers3d.value.map((l) => ({
      id: l.id,
      name: l.name,
      color: l.color,
      visible: l.visible,
    })),
    ...(partLayers.length > 0 ? { partLayers } : {}),
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
  const a = document.createElement('a')
  const stamp = new Date().toISOString().slice(0, 19).replace(/:/g, '-')
  a.href = URL.createObjectURL(blob)
  a.download = `assembly-project-${stamp}.json`
  a.click()
  URL.revokeObjectURL(a.href)
  logger.info('Viewer3D', `Проект сборки сохранён (${models.length} моделей, ${assemblyMatesOut.length} связей, ${partLayers.length} назначений слоёв)`)
}

function applyAssemblyProjectJson(data: unknown): { ok: boolean; message: string } {
  const obj = data as Partial<AssemblyProjectFileV1>
  if (obj?.format !== '3d-viewer-assembly-project' || obj.version !== 1 || !Array.isArray(obj.models)) {
    return { ok: false, message: 'Файл не похож на проект сборки (нужны format, version: 1 и models).' }
  }
  const nameToId = new Map<string, string>()
  for (const m of loadedModels.value) {
    if (!nameToId.has(m.name)) nameToId.set(m.name, m.id)
  }
  const missing = obj.models!.map((x) => x.modelName).filter((n) => !nameToId.has(n))
  if (missing.length > 0) {
    return {
      ok: false,
      message: `Загрузите те же 3D файлы (имена как в проекте). Не найдены: ${missing.join(', ')}`,
    }
  }
  for (const entry of obj.models!) {
    const id = nameToId.get(entry.modelName)
    if (!id) continue
    setModelInScene(id, entry.inScene ?? true)
  }
  for (const entry of obj.models!) {
    const id = nameToId.get(entry.modelName)
    const g = id ? modelGroupsById.get(id) : undefined
    if (g) {
      g.position.set(entry.px ?? 0, entry.py ?? 0, entry.pz ?? 0)
      g.rotation.set(entry.rx ?? 0, entry.ry ?? 0, entry.rz ?? 0)
    }
  }
  const importedMates: StoredAssemblyMate[] = []
  for (const raw of obj.assemblyMates ?? []) {
    const im = mateFromExported(raw as ExportedAssemblyMate, nameToId)
    if (im) importedMates.push(im)
  }
  assemblyMates.value = importedMates
  selectedAssemblyMateId.value = null
  meshGroup.updateMatrixWorld(true)
  if (Array.isArray(obj.sceneLayers) && obj.sceneLayers.length > 0) {
    sceneLayers3d.value = obj.sceneLayers.map((l) => ({
      id: String(l.id),
      name: String(l.name),
      color: String(l.color ?? '#e8eef8'),
      visible: l.visible !== false,
    }))
  }
  if (Array.isArray(obj.partLayers) && obj.partLayers.length > 0) {
    applyPartLayersFromProject(obj.partLayers)
  }
  refreshAfterAssemblyMove()
  refreshAllAssemblyVisuals()
  const layerInfo =
    Array.isArray(obj.partLayers) && obj.partLayers.length > 0
      ? `, слои: ${obj.sceneLayers?.length ?? sceneLayers3d.value.length}, назначений: ${obj.partLayers.length}`
      : ''
  assemblyStatus.value = `Проект загружен: ${obj.models!.length} моделей, ${importedMates.length} связей${layerInfo}.`
  logger.info('Viewer3D', assemblyStatus.value)
  return { ok: true, message: assemblyStatus.value }
}

function cancelActiveTool(): boolean {
  let cancelled = false
  if (measureModeRef.value) {
    setMeasureMode(false)
    cancelled = true
  }
  if (modelRotateMode.value) {
    modelRotateMode.value = false
    cancelled = true
  }
  if (assemblyPickTarget.value) {
    assemblyPickTarget.value = null
    cancelled = true
  }
  if (cadLinearPickTarget.value) {
    cadLinearPickTarget.value = null
    cancelled = true
  }
  if (placementActive.value) {
    cancelModelPlacement()
    cancelled = true
  }
  if (boxSelectDrag || boxSelectRect.value) {
    detachBoxSelectWindowListeners()
    boxSelectDrag = null
    boxSelectRect.value = null
    if (controls) controls.enabled = true
    cancelled = true
  }
  return cancelled
}

defineExpose({
  openFileDialog,
  loadModelFile,
  takeScreenshot,
  getLoadedFileName: () => loadedFileName,
  loadedModels,
  removeModel,
  setModelInScene,
  getMeasurementReport,
  resetView,
  setSectionAxis,
  setSectionOffset,
  getSectionOffset,
  isSectionActive,
  setSectionMode,
  clearSection,
  setMeasureMode,
  setMeasureSnapMode,
  getMeasureSnapMode,
  setMeasureType,
  clearMeasurements,
  exportGlb,
  exportStl,
  resizeViewport,
  saveAssemblyProjectJson,
  applyAssemblyProjectJson,
  setLeftSidebarTab,
  cancelActiveTool,
  undoLastAction: () => undoTransform(),
  openSettingsModal,
  closeSettingsModal,
  saveModel3dRemarksToFile,
  confirmDiscardModel3dRemarksAsync,
  get isRemarksDirty() {
    return remarksDirty.value
  },
})
</script>

<template>
  <div class="viewer-wrap">
    <header class="viewer-3d-header">
      <span class="viewer-3d-title">3D</span>
      <button type="button" class="viewer-3d-btn viewer-3d-btn-open-model" title="STL, STEP, IGES, GLB…" @click="openFileDialog">
        Открыть 3D
      </button>
      <div class="viewer-header-tabs">
        <button type="button" :class="{ active: headerToolsTab === 'viewTools' }" @click="headerToolsTab = 'viewTools'">Вид и инструменты</button>
        <button type="button" :class="{ active: headerToolsTab === 'display' }" @click="headerToolsTab = 'display'">Отображение</button>
        <button type="button" :class="{ active: headerToolsTab === 'export' }" @click="headerToolsTab = 'export'">Экспорт</button>
        <button type="button" class="viewer-settings-open-btn" title="Настройки сцены, мыши и цвета" @click="openSettingsModal">Настройки</button>
      </div>
      <div class="viewer-3d-tools">
        <div v-show="headerToolsTab === 'viewTools'" class="viewer-header-block" data-group="Вид и инструменты">
          <button type="button" class="viewer-3d-btn" @click="resetView">Вид по умолчанию</button>
          <div ref="orientationDropdownRef" class="viewer-orientation-dropdown">
          <button
            type="button"
            class="viewer-3d-btn viewer-orient-trigger"
            :class="{ open: orientationDropdownOpen }"
            :disabled="!loadedModels.some(m => m.inScene)"
            title="Ориентация вида"
            @click.stop="orientationDropdownOpen = !orientationDropdownOpen"
          >
            <svg class="viewer-orient-cube" viewBox="0 0 24 24" width="18" height="18">
              <path d="M12 2 L22 8 L22 18 L12 24 L2 18 L2 8 Z" fill="currentColor" opacity="0.4"/>
              <path d="M2 8 L12 2 L22 8 L12 14 Z" fill="currentColor" opacity="0.7"/>
              <path d="M12 2 L22 8 L12 14 L2 8 Z" fill="currentColor"/>
            </svg>
            Ориентация
          </button>
          <Transition name="viewer-orient-fade">
            <div v-show="orientationDropdownOpen" class="viewer-orientation-menu">
              <button
                v-for="opt in ORIENTATION_OPTIONS"
                :key="opt.id"
                type="button"
                class="viewer-orient-item"
                :title="opt.tooltip"
                @click="setViewOrientation(opt.id)"
              >
                <template v-if="opt.hasIcon">
                  <svg class="viewer-orient-cube-icon" viewBox="0 0 24 24" width="20" height="20">
                    <path d="M12 4 L20 8 L12 12 L4 8 Z" fill="currentColor" :opacity="opt.id === 'top' || opt.id === 'bottom' ? 1 : 0.35"/>
                    <path d="M4 8 L12 4 L12 12 L4 16 Z" fill="currentColor" :opacity="opt.id === 'back' || opt.id === 'left' ? 1 : 0.35"/>
                    <path d="M12 4 L20 8 L20 20 L12 24 L12 12 Z" fill="currentColor" :opacity="opt.id === 'front' || opt.id === 'right' ? 1 : 0.35"/>
                  </svg>
                  <span class="viewer-orient-label">{{ opt.label }}</span>
                </template>
                <span v-else class="viewer-orient-text-only">{{ opt.label }}</span>
              </button>
            </div>
          </Transition>
          </div>
          <button type="button" class="viewer-3d-btn" title="Фокус на модели (F)" @click="focusModelInView">Фокус</button>
          <button type="button" class="viewer-3d-btn" title="Перпендикулярно к выбранной грани" @click="viewPerpendicularToFace">Перпендикулярно</button>
          <button type="button" class="viewer-3d-btn" :class="{ active: showGroundGrid }" title="Сетка пола" @click="toggleGroundGrid">Сетка</button>
          <div ref="mouseSettingsDropdownRef" class="viewer-orientation-dropdown viewer-mouse-dropdown">
          <button
            type="button"
            class="viewer-3d-btn viewer-orient-trigger"
            :class="{ open: mouseSettingsDropdownOpen }"
            title="Скорость зума, вращения, направление колёсика"
            @click.stop="mouseSettingsDropdownOpen = !mouseSettingsDropdownOpen"
          >
            Настройки мыши
          </button>
          <Transition name="viewer-orient-fade">
            <div v-show="mouseSettingsDropdownOpen" class="viewer-orientation-menu viewer-mouse-menu">
              <div class="viewer-mouse-row">
                <label class="viewer-mouse-label" title="Максимальная дистанция камеры (отдаление)">Макс. отдаление</label>
                <input
                  v-model.number="mouseMaxDistance"
                  type="number"
                  min="1000"
                  max="500000"
                  step="1000"
                  class="viewer-mouse-input"
                  @change="autoNavLimitsEnabled = false; applyMouseSettings()"
                />
              </div>
              <div class="viewer-mouse-row">
                <label class="viewer-mouse-label" title="Минимальная дистанция (приближение)">Мин. приближение</label>
                <input
                  v-model.number="mouseMinDistance"
                  type="number"
                  min="1"
                  max="500"
                  class="viewer-mouse-input"
                  @change="autoNavLimitsEnabled = false; applyMouseSettings()"
                />
              </div>
              <div class="viewer-mouse-row viewer-mouse-row-check">
                <label class="viewer-mouse-label" title="Автоматически подстраивать пределы зума под размер модели">Автолимиты навигации</label>
                <input
                  v-model="autoNavLimitsEnabled"
                  type="checkbox"
                  class="viewer-mouse-check"
                  @change="onAutoNavLimitsChange"
                />
              </div>
              <div class="viewer-mouse-row">
                <label class="viewer-mouse-label" title="Шаг зума при прокрутке колёсика">Скорость зума</label>
                <input
                  v-model.number="mouseZoomSpeed"
                  type="number"
                  min="0.01"
                  max="0.09"
                  step="0.005"
                  class="viewer-mouse-input"
                  @change="applyMouseSettings"
                />
              </div>
              <div class="viewer-mouse-row viewer-mouse-row-check">
                <label class="viewer-mouse-label">Колёсико: к себе = отдаление</label>
                <input v-model="mouseInvertWheel" type="checkbox" class="viewer-mouse-check" />
              </div>
              <div class="viewer-mouse-row">
                <label class="viewer-mouse-label" title="Скорость вращения правой кнопкой">Скорость вращения</label>
                <input
                  v-model.number="mouseRotateSpeed"
                  type="number"
                  min="2.2"
                  max="8.8"
                  step="0.5"
                  class="viewer-mouse-input"
                  @change="applyMouseSettings"
                />
              </div>
              <div class="viewer-mouse-row">
                <label class="viewer-mouse-label" title="Скорость панорамирования средней кнопкой">Скорость панорамирования</label>
                <input
                  v-model.number="mousePanSpeed"
                  type="number"
                  min="0.7"
                  max="3.5"
                  step="0.5"
                  class="viewer-mouse-input"
                  @change="applyMouseSettings"
                />
              </div>
              <div class="viewer-mouse-row">
                <label class="viewer-mouse-label" title="Затухание инерции вращения">Затухание вращения</label>
                <input
                  v-model.number="mouseDamping"
                  type="number"
                  min="0.12"
                  max="0.4"
                  step="0.01"
                  class="viewer-mouse-input"
                  @change="applyMouseSettings"
                />
              </div>
              <div class="viewer-mouse-row">
                <label class="viewer-mouse-label" title="Через сколько мс без прокрутки сбрасывается точка зума">Сброс точки зума (мс)</label>
                <input
                  v-model.number="mouseZoomGestureMs"
                  type="number"
                  min="180"
                  max="900"
                  step="50"
                  class="viewer-mouse-input"
                  @change="applyMouseSettings"
                />
              </div>
              <div class="viewer-mouse-row viewer-mouse-row-check">
                <label class="viewer-mouse-label" title="Перетаскивание детали в сцене левой кнопкой">Левая кнопка: перемещение модели в сцене</label>
                <input v-model="leftButtonMoveModel" type="checkbox" class="viewer-mouse-check" />
              </div>
            </div>
          </Transition>
          </div>
          <button type="button" class="viewer-3d-btn" :class="{ active: sectionMode }" @click="emit('section-mode')">Сечение</button>
          <button type="button" class="viewer-3d-btn btn-fix" title="Зафиксировать сечение" @click="emit('fix-section')">✓</button>
          <button type="button" class="viewer-3d-btn btn-clear" title="Снять сечение" @click="emit('clear-section')">✕</button>
          <template v-if="sectionActive">
            <input
              type="number"
              class="viewer-3d-offset"
              :min="SECTION_OFFSET_MIN"
              :max="SECTION_OFFSET_MAX"
              :step="SECTION_OFFSET_STEP"
              :value="sectionOffset ?? 0"
              @input="onHeaderOffsetInput"
              @wheel.prevent="onHeaderOffsetWheel($event, sectionOffset ?? 0)"
            />
            <input
              type="range"
              class="viewer-3d-slider"
              :min="SECTION_OFFSET_MIN"
              :max="SECTION_OFFSET_MAX"
              :step="SECTION_OFFSET_STEP"
              :value="sectionOffset ?? 0"
              @input="onHeaderOffsetInput"
            />
          </template>
          <button type="button" class="viewer-3d-btn" :class="{ active: measureModeRef || (leftSidebarTab === 'params' && paramsSubTab === 'measurements') }" @click="onMeasureHeaderClick">Измерение</button>
          <button
            type="button"
            class="viewer-3d-btn"
            :class="{ active: !!(focusedModelId && pinnedByModelId[focusedModelId]) }"
            :disabled="!focusedModelId"
            title="Закрепить модель в сцене (Ctrl+C / Ctrl+V — копировать положение)"
            @click="togglePinFocusedModel"
          >
            {{ focusedModelId && pinnedByModelId[focusedModelId] ? 'Открепить' : 'Закрепить' }}
          </button>
          <button
            type="button"
            class="viewer-3d-btn"
            :class="{ active: modelRotateMode }"
            :disabled="!focusedModelId"
            title="Вращение выбранной модели вокруг центра габарита (горизонталь мыши — ось Y мира, вертикаль — ось X). Esc — выключить"
            @click="modelRotateMode = !modelRotateMode"
          >
            Вращение
          </button>
          <button type="button" class="viewer-3d-btn" :class="{ active: leftSidebarTab === 'params' && paramsSubTab === 'assembly' }" @click="onAssemblyHeaderClick">Сборка</button>
        </div>
        <div v-show="headerToolsTab === 'display'" class="viewer-header-block viewer-header-block-frame" data-group="Отображение">
          <button
            type="button"
            class="viewer-3d-btn"
            :class="{ active: wireframeModeRef }"
            :title="`Каркас: линии по контуру деталей (яркость ${frameOpacityRef}). Прозрачность граней — ПКМ по детали.`"
            @click="toggleWireframe"
          >
            Каркас
          </button>
          <input
            type="number"
            class="viewer-frame-opacity-input"
            :min="FRAME_OPACITY_MIN"
            :max="FRAME_OPACITY_MAX"
            :step="FRAME_OPACITY_STEP"
            :value="frameOpacityRef"
            title="Яркость линий каркаса"
            @input="onFrameOpacityInput"
            @wheel.prevent="onFrameOpacityWheel"
          />
          <input
            type="range"
            class="viewer-frame-opacity-slider"
            :min="FRAME_OPACITY_MIN"
            :max="FRAME_OPACITY_MAX"
            :step="FRAME_OPACITY_STEP"
            :value="frameOpacityRef"
            title="Яркость линий каркаса"
            @input="onFrameOpacityInput"
          />
          <label class="viewer-scene-shading" title="Режим шейдинга модели">
            <span>Свет</span>
            <select class="viewer-scene-select" :value="shadingMode" @change="onShadingModeChange">
              <option value="lit">Обычный</option>
              <option value="unlit">Светлый</option>
            </select>
          </label>
          <label class="viewer-scene-shading" title="Пресет освещения">
            <span>Пресет</span>
            <select class="viewer-scene-select" :value="lightPreset" @change="onLightPresetChange">
              <option value="engineering">Инженерный</option>
              <option value="soft">Мягкий</option>
            </select>
          </label>
          <label class="viewer-scene-shading" title="Яркость оттенка">
            <span>Тон</span>
            <input
              type="range"
              class="viewer-scene-tint-range"
              :min="TINT_BRIGHTNESS_MIN"
              :max="TINT_BRIGHTNESS_MAX"
              :step="TINT_BRIGHTNESS_STEP"
              :value="tintBrightness"
              @input="onTintBrightnessInput"
              @wheel.prevent="onTintBrightnessWheel"
            />
          </label>
          <label
            class="viewer-scene-shading viewer-explode-control"
            title="Крупнейшая деталь закреплена; остальные разъезжаются от неё и друг от друга (% × макс. габарит)."
          >
            <span>Разнос</span>
            <input
              type="range"
              class="viewer-frame-opacity-slider"
              :min="EXPLODE_MIN"
              :max="EXPLODE_MAX"
              :step="EXPLODE_STEP"
              :value="explodeAmount"
              @input="onExplodeInput"
            />
            <input
              type="number"
              class="viewer-frame-opacity-input"
              :min="EXPLODE_MIN"
              :max="EXPLODE_MAX"
              :step="EXPLODE_STEP"
              :value="explodeAmount"
              title="Процент от макс. габарита (0 — собрано, 100 — вся большая сторона)"
              @input="onExplodeInput"
            />
            <span v-if="explodeTravelHint != null" class="viewer-explode-mm-hint">{{ explodeTravelHint.pct }}% ≈{{ explodeTravelHint.mm }} мм</span>
            <button type="button" class="viewer-3d-btn viewer-explode-reset" title="Сбросить разнесение" @click="resetExplodeAmount">0</button>
          </label>
        </div>
        <div v-show="headerToolsTab === 'export'" class="viewer-header-block" data-group="Экспорт">
          <button type="button" class="viewer-3d-btn" @click="emit('screenshot-3d')">Скриншот 3D</button>
          <button type="button" class="viewer-3d-btn" @click="exportGlb">Экспорт GLB</button>
          <button type="button" class="viewer-3d-btn" @click="exportStl">Экспорт STL</button>
        </div>
      </div>
    </header>
    <div class="viewer-body">
      <div class="viewer-left-sidebar">
        <div class="viewer-left-sidebar-tabs viewer-left-sidebar-tabs--kompas" role="tablist" aria-label="Панель 3D">
          <button type="button" class="viewer-left-tab" role="tab" title="Дерево модели" :class="{ active: leftSidebarTab === 'tree' }" @click="setLeftSidebarTab('tree')">
            <ViewerSidebarIcons name="tree" />
          </button>
          <button type="button" class="viewer-left-tab" role="tab" title="Параметры" :class="{ active: leftSidebarTab === 'params' }" @click="setParamsSubTab('assembly')">
            <ViewerSidebarIcons name="params" />
          </button>
          <button type="button" class="viewer-left-tab" role="tab" title="Дерево слоёв" :class="{ active: leftSidebarTab === 'layers' }" @click="setLeftSidebarTab('layers')">
            <ViewerSidebarIcons name="layers" />
          </button>
          <button type="button" class="viewer-left-tab" role="tab" title="Библиотека" :class="{ active: leftSidebarTab === 'library' }" @click="setLeftSidebarTab('library')">
            <ViewerSidebarIcons name="library" />
          </button>
        </div>
        <div v-show="leftSidebarTab === 'params'" class="viewer-params-subtabs" role="tablist">
          <button type="button" class="viewer-params-subtab" :class="{ active: paramsSubTab === 'assembly' }" @click="setParamsSubTab('assembly')">Сборка</button>
          <button type="button" class="viewer-params-subtab" :class="{ active: paramsSubTab === 'measurements' }" @click="setParamsSubTab('measurements')">Измерения</button>
          <button type="button" class="viewer-params-subtab" :class="{ active: paramsSubTab === 'selection' }" @click="setParamsSubTab('selection')">Выделение</button>
          <button type="button" class="viewer-params-subtab" :class="{ active: paramsSubTab === 'remarks' }" @click="setParamsSubTab('remarks')">Замечания</button>
        </div>
        <div v-show="leftSidebarTab === 'tree'" class="viewer-left-sidebar-pane">
        <div class="viewer-models-header">
          <span class="viewer-models-title">Дерево модели</span>
          <span class="viewer-models-count">({{ loadedModels.length }})</span>
          <button type="button" class="viewer-models-add" title="Добавить модель" @click="openFileDialog">+</button>
        </div>
        <div class="viewer-models-metrics">
          {{ sceneMetricsText }}
        </div>
        <div v-if="loadedModels.length === 0" class="viewer-models-empty">
          Откройте модель или перетащите файлы (STL, STEP, IGES). В сцене — до {{ MAX_MODELS_IN_SCENE }}, загрузка — до {{ MAX_FILES_SELECT }} за раз.
        </div>
        <template v-else>
        <div class="viewer-tree-actions">
          <button type="button" class="viewer-placement-btn" title="Снять подсветку и затемнение" @click="resetPartSelectionAndView">Сбросить выделение</button>
          <button type="button" class="viewer-placement-btn viewer-placement-btn-primary" title="Вернуть цвета из STEP/meta" @click="restoreOriginalModelColors()">Исходные цвета</button>
        </div>
        <label
          class="viewer-tree-explode"
          title="Крупнейшая деталь закреплена, остальные группы дерева разъезжаются от её центра."
        >
          <span>Разнесение деталей</span>
          <input
            type="range"
            class="viewer-tree-explode-slider"
            :min="EXPLODE_MIN"
            :max="EXPLODE_MAX"
            :step="EXPLODE_STEP"
            :value="explodeAmount"
            @input="onExplodeInput"
          />
          <span class="viewer-tree-explode-val">{{ explodeAmount }}%<template v-if="explodeTravelHint != null"> ≈{{ explodeTravelHint.mm }} мм</template></span>
          <button type="button" class="viewer-placement-btn" @click="resetExplodeAmount">Сброс</button>
        </label>
        <label class="viewer-tree-isolate-check">
          <input v-model="partIsolateDimOthers" type="checkbox" @change="partIsolateDimOthers ? applySelectionVisualsAndFocus() : clearPartFocusVisuals()" />
          <span>Затемнять остальные при выделении (тяжело на больших сборках)</span>
        </label>
        <div class="viewer-models-hint">
          Клик — одна деталь. Рамка (при загруженной модели): слева направо — синяя, справа налево — зелёная. Ctrl/Shift — добавить. Двойной клик в дереве — изоляция. ПКМ — прозрачность.
        </div>
        <div v-if="placementActive" class="viewer-placement-panel">
          <div class="viewer-placement-title">Размещение модели</div>
          <p v-if="placementStatusHint" class="viewer-placement-hint">{{ placementStatusHint }}</p>
          <div class="viewer-placement-coords">
            <label class="viewer-placement-field">
              <span>X</span>
              <input v-model.number="placementPosMm.x" type="number" step="0.1" class="viewer-placement-input" @change="applyPlacementFromFields" />
            </label>
            <label class="viewer-placement-field">
              <span>Y</span>
              <input v-model.number="placementPosMm.y" type="number" step="0.1" class="viewer-placement-input" @change="applyPlacementFromFields" />
            </label>
            <label class="viewer-placement-field">
              <span>Z</span>
              <input v-model.number="placementPosMm.z" type="number" step="0.1" class="viewer-placement-input" @change="applyPlacementFromFields" />
            </label>
          </div>
          <div class="viewer-placement-actions">
            <button type="button" class="viewer-placement-btn" @click="applyPlacementFromFields">Применить</button>
            <button type="button" class="viewer-placement-btn viewer-placement-btn-primary" @click="confirmModelPlacement">Зафиксировать</button>
            <button type="button" class="viewer-placement-btn" @click="cancelModelPlacement">Отмена</button>
          </div>
        </div>
        <div class="viewer-model-accordion">
          <div
            v-for="item in loadedModels"
            :key="item.id"
            class="viewer-model-accordion-item"
            :class="{
              'viewer-model-accordion-focused': focusedModelId === item.id,
              'viewer-model-accordion-hidden': !item.inScene,
            }"
          >
            <div
              class="viewer-model-accordion-header"
              :class="{ 'viewer-model-accordion-header-active': focusedModelId === item.id }"
              title="Клик — фокус и зум к модели; двойной клик — камера на модель (F)"
              @click="onModelTreeHeaderClick(item)"
              @dblclick="onModelTreeHeaderDblClick(item)"
            >
              <button
                type="button"
                class="viewer-model-accordion-chevron"
                :title="isModelExpanded(item.id) ? 'Свернуть' : 'Развернуть'"
                @click.stop="toggleModelExpanded(item.id)"
              >
                {{ isModelExpanded(item.id) ? '▼' : '▶' }}
              </button>
              <span class="viewer-model-accordion-name" :title="item.name">{{ item.name }}</span>
              <button
                type="button"
                class="viewer-component-item-eye-btn"
                :title="modelPartsAnyVisible(item.id) && item.inScene ? 'Скрыть все детали' : 'Показать все детали'"
                @click.stop="toggleModelPartsVisibility(item.id)"
              >
                {{ modelPartsAnyVisible(item.id) && item.inScene ? '👁' : '🚫' }}
              </button>
              <button
                v-if="item.inScene"
                type="button"
                class="viewer-models-btn"
                title="Убрать из сцены"
                @click.stop="setModelInScene(item.id, false)"
              >
                ⊖
              </button>
              <button
                v-else
                type="button"
                class="viewer-models-btn viewer-models-btn-add"
                title="Добавить в сцену"
                @click.stop="setModelInScene(item.id, true)"
              >
                ⊕
              </button>
              <button type="button" class="viewer-models-btn viewer-models-btn-remove" title="Удалить модель" @click.stop="removeModel(item.id)">×</button>
            </div>
            <div v-if="isModelExpanded(item.id)" class="viewer-model-accordion-parts">
              <div v-if="modelTreeRows(item.id).length === 0" class="viewer-component-tree-empty">
                Нет отдельных деталей в сцене.
              </div>
              <div
                v-for="row in modelTreeRows(item.id)"
                :key="row.id"
                class="viewer-component-item"
                :class="{
                  'viewer-component-item-selected': selectedPartRowKeys.has(`${item.id}:${row.id}`),
                  'viewer-component-item-category': row.nodeKind === 'category',
                }"
                :style="{ paddingLeft: `${8 + row.depth * 14}px` }"
                title="Клик — выделение; двойной клик — изоляция (скрыть остальные, деталь в цвете)"
                @click="selectComponentRow(item.id, row.id, $event)"
                @dblclick.stop="selectComponentRowAndFocus(item.id, row.id)"
              >
                <span v-if="row.nodeKind === 'category'" class="viewer-component-item-chevron">{{ isCategoryExpandedForRow(row.id) ? '▼' : '▶' }}</span>
                <span class="viewer-component-item-label" :class="{ 'viewer-component-item-label--category': row.nodeKind === 'category' }">{{ row.label }}</span>
                <span v-if="row.targetIds.length > 1" class="viewer-component-item-count">×{{ row.targetIds.length }}</span>
                <span class="viewer-component-item-spacer"></span>
                <button
                  v-if="row.targetIds.length > 0"
                  type="button"
                  class="viewer-component-item-eye-btn"
                  :title="row.visible ? 'Скрыть' : 'Показать'"
                  @click.stop="toggleComponentVisibility(item.id, row.id)"
                >
                  {{ row.visible ? '👁' : '🚫' }}
                </button>
              </div>
            </div>
          </div>
        </div>
        </template>
        </div>
        <div v-show="leftSidebarTab === 'params' && paramsSubTab === 'assembly'" class="viewer-left-sidebar-pane viewer-sidebar-panel">
          <div class="viewer-assembly-body viewer-assembly-body--sidebar">
            <div class="viewer-assembly-row">
              <label>Тип сопряжения</label>
              <select v-model="assemblyMateType" class="viewer-assembly-select">
                <option value="plane">По плоскостям</option>
                <option value="distance">На расстоянии</option>
                <option value="symmetric">Симметрия по ширине</option>
                <option value="coord">К координатным плоскостям</option>
              </select>
            </div>
            <div class="viewer-assembly-row">
              <label>Источник</label>
              <select v-model="assemblySourceModelId" class="viewer-assembly-select">
                <option value="">— выберите —</option>
                <option v-for="m in visibleAssemblyModels" :key="'src-mini-' + m.id" :value="m.id">{{ m.name }}</option>
              </select>
            </div>
            <div v-if="assemblyMateType !== 'coord'" class="viewer-assembly-row">
              <label>Опорная</label>
              <select v-model="assemblyTargetModelId" class="viewer-assembly-select">
                <option value="">— выберите —</option>
                <option v-for="m in visibleAssemblyModels" :key="'dst-mini-' + m.id" :value="m.id">{{ m.name }}</option>
              </select>
            </div>
            <template v-if="assemblyMateType === 'coord'">
              <div class="viewer-assembly-row">
                <label>Плоскость модели</label>
                <div class="viewer-assembly-pick">
                  <input class="viewer-assembly-input viewer-assembly-input-pick" :value="assemblySourcePlaneText" readonly />
                  <button type="button" class="viewer-assembly-pick-btn" @click="startAssemblyPlanePick('source')">Выбрать</button>
                </div>
              </div>
              <div class="viewer-assembly-row">
                <label>Координатная плоскость</label>
                <select v-model="assemblyCoordWorldPlane" class="viewer-assembly-select" @change="refreshAllAssemblyVisuals">
                  <option v-for="opt in WORLD_COORD_PLANE_OPTIONS" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
                </select>
              </div>
              <div class="viewer-assembly-note viewer-assembly-note-coord">
                {{ WORLD_COORD_PLANE_OPTIONS.find((o) => o.id === assemblyCoordWorldPlane)?.hint }}
              </div>
              <label class="viewer-assembly-row-check">
                <input v-model="assemblyCoordFlipNormal" type="checkbox" @change="refreshAllAssemblyVisuals" />
                <span>Развернуть нормаль (обратная сторона)</span>
              </label>
              <div class="viewer-assembly-row">
                <label>Смещение, мм</label>
                <input v-model.number="assemblyDistanceMm" type="number" class="viewer-assembly-input" min="0" step="0.1" />
              </div>
              <div class="viewer-assembly-note">
                Плоскости XY, XZ, YZ проходят через начало координат сцены. Для выравнивания по двум осям примените два сопряжения к разным граням.
              </div>
            </template>
            <template v-else-if="assemblyMateType === 'symmetric'">
              <div class="viewer-assembly-row">
                <label>База: плоскость 1</label>
                <div class="viewer-assembly-pick">
                  <input class="viewer-assembly-input viewer-assembly-input-pick" :value="assemblySymBase1Text" readonly />
                  <button type="button" class="viewer-assembly-pick-btn" @click="startAssemblyPlanePick('symBase1')">Выбрать</button>
                </div>
              </div>
              <div class="viewer-assembly-row">
                <label>База: плоскость 2</label>
                <div class="viewer-assembly-pick">
                  <input class="viewer-assembly-input viewer-assembly-input-pick" :value="assemblySymBase2Text" readonly />
                  <button type="button" class="viewer-assembly-pick-btn" @click="startAssemblyPlanePick('symBase2')">Выбрать</button>
                </div>
              </div>
              <div class="viewer-assembly-row">
                <label>Деталь: плоскость 1</label>
                <div class="viewer-assembly-pick">
                  <input class="viewer-assembly-input viewer-assembly-input-pick" :value="assemblySymPart1Text" readonly />
                  <button type="button" class="viewer-assembly-pick-btn" @click="startAssemblyPlanePick('symPart1')">Выбрать</button>
                </div>
              </div>
              <div class="viewer-assembly-row">
                <label>Деталь: плоскость 2</label>
                <div class="viewer-assembly-pick">
                  <input class="viewer-assembly-input viewer-assembly-input-pick" :value="assemblySymPart2Text" readonly />
                  <button type="button" class="viewer-assembly-pick-btn" @click="startAssemblyPlanePick('symPart2')">Выбрать</button>
                </div>
              </div>
            </template>
            <template v-else>
              <div class="viewer-assembly-row">
                <label>Плоскость источника</label>
                <div class="viewer-assembly-pick">
                  <input class="viewer-assembly-input viewer-assembly-input-pick" :value="assemblySourcePlaneText" readonly />
                  <button type="button" class="viewer-assembly-pick-btn" @click="startAssemblyPlanePick('source')">Выбрать</button>
                </div>
              </div>
              <div class="viewer-assembly-row">
                <label>Плоскость опорной</label>
                <div class="viewer-assembly-pick">
                  <input class="viewer-assembly-input viewer-assembly-input-pick" :value="assemblyTargetPlaneText" readonly />
                  <button type="button" class="viewer-assembly-pick-btn" @click="startAssemblyPlanePick('target')">Выбрать</button>
                </div>
              </div>
            </template>
            <div v-if="assemblyMateType === 'distance'" class="viewer-assembly-row">
              <label>Расстояние, мм</label>
              <input v-model.number="assemblyDistanceMm" type="number" class="viewer-assembly-input" min="0" step="0.1" />
            </div>
            <div class="viewer-assembly-world-csys">
              <button
                type="button"
                class="viewer-assembly-world-csys-title"
                @click="worldCoordSystemExpanded = !worldCoordSystemExpanded"
              >
                {{ worldCoordSystemExpanded ? '▼' : '▶' }} Мировая СК (ноль сцены)
              </button>
              <div v-show="worldCoordSystemExpanded" class="viewer-assembly-world-csys-body">
                <label class="viewer-assembly-row-check">
                  <input v-model="showWorldCoordSystem" type="checkbox" @change="syncWorldCoordSystemGroup" />
                  <span>Показать оси и плоскости в сцене</span>
                </label>
                <div class="viewer-assembly-world-plane-btns">
                  <button
                    v-for="opt in WORLD_COORD_PLANE_OPTIONS"
                    :key="opt.id"
                    type="button"
                    class="viewer-assembly-world-plane-btn"
                    :class="{ active: assemblyCoordWorldPlane === opt.id }"
                    :title="opt.hint"
                    @click="selectWorldCoordPlane(opt.id)"
                  >
                    {{ opt.label }}
                  </button>
                </div>
                <div class="viewer-assembly-note">
                  Начало координат — (0, 0, 0) сцены. Плоскости для сопряжения «К координатным»; не привязаны к деталям.
                </div>
              </div>
            </div>
            <button type="button" class="viewer-assembly-apply" @click="applyAssemblyMate">Применить сопряжение</button>
            <button type="button" class="viewer-assembly-apply" :disabled="assemblyMates.length === 0" @click="clearAllAssemblyMates">Очистить сопряжения</button>
            <div class="viewer-assembly-note">Плоская грань: «Выбрать» → клик по грани. Модель повернётся к выбранной плоскости (мировой или опорной).</div>
            <div v-if="assemblyStatus" class="viewer-assembly-status">{{ assemblyStatus }}</div>
            <div v-if="assemblyMates.length > 0" class="viewer-assembly-mates">
              <div class="viewer-assembly-mates-title">Связи</div>
              <div
                v-for="(m, idx) in assemblyMates"
                :key="m.id"
                class="viewer-assembly-mate-row"
                :class="{ 'viewer-assembly-mate-row-active': selectedAssemblyMateId === m.id }"
                tabindex="0"
                @click="selectAssemblyMateRow(m.id)"
              >
                <span class="viewer-assembly-mate-no">#{{ idx + 1 }}</span>
                <span class="viewer-assembly-mate-type">{{ assemblyMateTypeLabel(m) }}</span>
                <button type="button" class="viewer-assembly-mate-del" title="Удалить связь" @click.stop="removeAssemblyMate(m.id)">×</button>
              </div>
            </div>
          </div>
        </div>
        <div v-show="leftSidebarTab === 'params' && paramsSubTab === 'selection'" class="viewer-left-sidebar-pane viewer-sidebar-panel viewer-selection-panel">
          <div class="viewer-selection-header">Выделение и слои</div>
          <p class="viewer-models-hint">{{ selectedPartsSummary }}</p>
          <p class="viewer-models-hint">
            Рамка на сцене (при загруженной модели): слева направо — синяя (полностью внутри), справа налево — зелёная (пересечение). Ctrl/Shift — добавить к выделению.
          </p>
          <div class="viewer-selection-row">
            <label>Слой</label>
            <select v-model="selectedLayerAssignId" class="viewer-assembly-select">
              <option v-for="layer in sceneLayers3d" :key="layer.id" :value="layer.id">{{ layer.name }}</option>
            </select>
            <button type="button" class="viewer-placement-btn viewer-placement-btn-primary" @click="assignSelectedPartsToLayer(selectedLayerAssignId)">
              Назначить
            </button>
          </div>
          <div class="viewer-selection-row">
            <label>Цвет</label>
            <input type="color" class="viewer-selection-color" value="#6699cc" @change="applyLayerColorToSelected(($event.target as HTMLInputElement).value)" />
          </div>
          <button type="button" class="viewer-placement-btn" @click="resetPartSelectionAndView">Снять выделение</button>
          <button type="button" class="viewer-placement-btn" @click="restoreOriginalModelColors()">Исходные цвета</button>
        </div>
        <div v-show="leftSidebarTab === 'params' && paramsSubTab === 'measurements'" class="viewer-left-sidebar-pane viewer-sidebar-panel viewer-measurements-sidebar">
          <div class="viewer-measurements-header">
            <span>Измерения</span>
            <button type="button" class="viewer-measurements-clear" @click="clearMeasurementHistory">очистить</button>
          </div>
          <div class="viewer-measurements-controls">
            <select class="viewer-measurements-select" :value="measureTypeRef" @change="setMeasureType(($event.target as HTMLSelectElement).value as MeasureType)">
              <optgroup label="Основные">
                <option value="distance">Расстояние (2 клика, live)</option>
                <option value="cad-linear">Между параллельными гранями</option>
              </optgroup>
            </select>
            <p v-if="measureStatusHint" class="viewer-measurements-hint">{{ measureStatusHint }}</p>
            <div class="viewer-measurements-dim-row">
              <span>Стрелка</span>
              <input v-model.number="dimArrowSizeMm" type="number" class="viewer-measurements-dim-input" min="2" max="60" step="0.5" />
              <span>Вынос</span>
              <input v-model.number="dimLineOffsetMm" type="number" class="viewer-measurements-dim-input" min="2" max="400" step="1" />
            </div>
            <div class="viewer-measurements-dim-row">
              <span>Шрифт</span>
              <input v-model.number="dimFontSizeMm" type="number" class="viewer-measurements-dim-input" min="6" max="80" step="1" />
              <span />
              <button type="button" class="viewer-measurements-cad-btn" @click="setMeasureMode(!measureModeRef)">
                {{ measureModeRef ? 'Измерение: вкл' : 'Измерение: выкл' }}
              </button>
            </div>
            <div v-if="measureTypeRef === 'cad-linear'" class="viewer-measurements-cad-row">
              <label>Три шага: грань 1 → грань 2 → плоскость вывода (или авто-вынос)</label>
              <div class="viewer-measurements-cad-pick">
                <input class="viewer-measurements-cad-input" :value="cadLinearPlane1Text" readonly title="1-я грань" />
                <button type="button" class="viewer-measurements-cad-btn" @click="startCadLinearPlanePick('plane1')">Грань 1</button>
              </div>
              <div class="viewer-measurements-cad-pick">
                <input class="viewer-measurements-cad-input" :value="cadLinearPlane2Text" readonly title="2-я грань" />
                <button type="button" class="viewer-measurements-cad-btn" @click="startCadLinearPlanePick('plane2')">Грань 2</button>
              </div>
              <div class="viewer-measurements-cad-pick viewer-measurements-cad-pick--optional">
                <input class="viewer-measurements-cad-input" :value="cadLinearDisplayPlaneText || '—'" readonly title="Плоскость выноса" />
                <button type="button" class="viewer-measurements-cad-btn" @click="startCadLinearPlanePick('display')">Вынос (3-я грань)</button>
                <button type="button" class="viewer-measurements-cad-btn" @click="autoCadLinearDisplayAndSave">Авто-вынос</button>
              </div>
              <button type="button" class="viewer-measurements-cad-new" @click="startNewCadLinearMeasurement">Новый размер</button>
              <div v-if="cadLinearStatus" class="viewer-measurements-cad-status">{{ cadLinearStatus }}</div>
            </div>
          </div>
          <div v-if="measurementHistory.length === 0" class="viewer-measurements-empty">Пока нет измерений.</div>
          <div v-else class="viewer-measurements-list">
            <div
              v-for="(m, idx) in measurementHistory.slice(0, 12)"
              :key="m.id"
              class="viewer-measurements-row"
              :class="{ active: selectedMeasurementId === m.id }"
              @click="restoreMeasurement(m)"
            >
              <span class="viewer-measurements-cell-id">#{{ measurementHistory.length - idx }}</span>
              <span>{{ measurementTypeLabel(m) }}</span>
              <span class="viewer-measurements-cell-value">{{ measurementValueText(m) }}</span>
              <button
                type="button"
                class="viewer-measurements-row-del"
                title="Удалить измерение"
                @click.stop="removeMeasurement(m.id)"
              >
                ×
              </button>
            </div>
          </div>
        </div>
        <div v-show="leftSidebarTab === 'params' && paramsSubTab === 'remarks'" class="viewer-left-sidebar-pane viewer-sidebar-panel viewer-remarks-panel">
          <p class="viewer-remarks-hint">
            Замечание запоминает ракурс камеры и разметку на экране (screenLayer). Якорь на детали остаётся при орбите.
            JSON сохраняется рядом с моделью; картинки — в том же файле (dataUrl) или в папке *_assets при экспорте.
          </p>
          <p v-if="!primaryModelFileName" class="viewer-remarks-empty">Загрузите модель в сцену.</p>
          <template v-else>
            <p class="viewer-remarks-model" :title="primaryModelFileName">{{ primaryModelFileName }}</p>
            <div class="viewer-remarks-actions">
              <button type="button" class="viewer-remarks-btn viewer-remarks-btn--primary" @click="addRemarkFromCurrentView">
                + Замечание
              </button>
              <button type="button" class="viewer-remarks-btn" @click="importModel3dRemarksFile">Открыть JSON</button>
            </div>
            <div class="viewer-remarks-filter-row">
              <label class="viewer-remarks-filter-label">Статус</label>
              <select v-model="remarkStatusFilter" class="viewer-remarks-filter-select">
                <option value="all">Все</option>
                <option v-for="opt in REMARK_STATUS_OPTIONS" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </div>
            <button
              v-if="selectedRemarkId"
              type="button"
              class="viewer-remarks-btn viewer-remarks-btn--block"
              @click="restoreSelectedRemarkView"
            >
              Вернуть вид замечания
            </button>
            <p
              v-if="selectedRemark && !remarkScreenLayerVisible"
              class="viewer-remarks-view-hint"
            >
              Разметка привязана к ракурсу (отклонение {{ remarkViewAngleDeg.toFixed(0) }}°). «Вернуть вид» — показать screenLayer.
            </p>
            <p v-if="selectedRemark && remarkScreenLayerVisible" class="viewer-remarks-nav-hint">
              ◇ — вращение модели; рисование — другой инструмент. Del — удалить выбранное. Картинка: колёсико — зум.
            </p>
            <div v-if="selectedRemark" class="viewer-remarks-markup-bar">
              <button
                type="button"
                class="viewer-remarks-markup-btn"
                :class="{ active: remarkScreenTool === 'select' }"
                :disabled="!remarkScreenLayerEditable"
                title="Выделение и вращение модели"
                @click="remarkScreenTool = 'select'"
              >
                ◇
              </button>
              <button
                type="button"
                class="viewer-remarks-markup-btn"
                :class="{ active: remarkAnchorPickMode }"
                @click="toggleRemarkAnchorPick"
              >
                {{ remarkAnchorPickMode ? 'Якорь: клик…' : 'Якорь' }}
              </button>
              <button
                v-if="selectedRemark.anchor3d"
                type="button"
                class="viewer-remarks-markup-btn"
                @click="clearSelectedRemarkAnchor"
              >
                Снять якорь
              </button>
              <button
                type="button"
                class="viewer-remarks-markup-btn"
                :class="{ active: remarkScreenTool === 'arrow' }"
                :disabled="!remarkScreenLayerEditable"
                @click="remarkScreenTool = 'arrow'"
              >
                →
              </button>
              <button
                type="button"
                class="viewer-remarks-markup-btn"
                :class="{ active: remarkScreenTool === 'line' }"
                :disabled="!remarkScreenLayerEditable"
                @click="remarkScreenTool = 'line'"
              >
                —
              </button>
              <button
                type="button"
                class="viewer-remarks-markup-btn"
                :class="{ active: remarkScreenTool === 'polyline' }"
                :disabled="!remarkScreenLayerEditable"
                title="Клики — точки; Enter — завершить"
                @click="remarkScreenTool = 'polyline'"
              >
                ⌇
              </button>
              <button
                type="button"
                class="viewer-remarks-markup-btn"
                :class="{ active: remarkScreenTool === 'rect' }"
                :disabled="!remarkScreenLayerEditable"
                @click="remarkScreenTool = 'rect'"
              >
                □
              </button>
              <button
                type="button"
                class="viewer-remarks-markup-btn"
                :class="{ active: remarkScreenTool === 'ellipse' }"
                :disabled="!remarkScreenLayerEditable"
                @click="remarkScreenTool = 'ellipse'"
              >
                ○
              </button>
              <button
                type="button"
                class="viewer-remarks-markup-btn"
                :class="{ active: remarkScreenTool === 'text' }"
                :disabled="!remarkScreenLayerEditable"
                @click="remarkScreenTool = 'text'"
              >
                T
              </button>
              <button
                type="button"
                class="viewer-remarks-markup-btn"
                :disabled="!remarkScreenLayerEditable"
                @click="insertRemarkScreenImage"
              >
                Картинка
              </button>
              <input v-model="remarkScreenColor" type="color" class="viewer-remarks-color" title="Цвет" />
              <button
                v-if="remarkScreenSelectedShapeId || remarkScreenSelectedImageId"
                type="button"
                class="viewer-remarks-markup-btn viewer-remarks-markup-btn--danger"
                @click="deleteSelectedScreenMarkup"
              >
                Удалить (Del)
              </button>
            </div>
            <ul v-if="remarkList.length" class="viewer-remarks-list">
              <li
                v-for="c in filteredRemarkList"
                :key="c.id"
                class="viewer-remarks-item"
                :class="{ active: selectedRemarkId === c.id }"
              >
                <button type="button" class="viewer-remarks-item-btn" @click="selectRemark(c.id)">
                  <span class="viewer-remarks-item-head">
                    <span class="remark-status-pill" :class="remarkStatusCssClass(normalizeRemarkStatus(c.status))">
                      {{ remarkStatusLabel(normalizeRemarkStatus(c.status)) }}
                    </span>
                    <span class="viewer-remarks-item-title">{{ c.title }}</span>
                  </span>
                  <span class="viewer-remarks-item-meta">{{ new Date(c.createdAt).toLocaleString() }}</span>
                </button>
                <button
                  type="button"
                  class="viewer-remarks-item-del"
                  title="Удалить замечание"
                  @click.stop="deleteRemarkById(c.id)"
                >
                  ×
                </button>
              </li>
            </ul>
            <p v-if="remarkList.length && filteredRemarkList.length === 0" class="viewer-remarks-empty">
              Нет замечаний с выбранным статусом.
            </p>
            <p v-else-if="!remarkList.length" class="viewer-remarks-empty">Нет замечаний — «+ Замечание» с нужного ракурса.</p>
            <div v-if="selectedRemark" class="viewer-remark-detail">
              <label class="viewer-remark-detail-label">Статус</label>
              <select
                class="viewer-remarks-filter-select"
                :value="normalizeRemarkStatus(selectedRemark.status)"
                @change="updateSelectedRemarkStatus(($event.target as HTMLSelectElement).value as RemarkStatus)"
              >
                <option v-for="opt in REMARK_STATUS_OPTIONS" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
              <label class="viewer-remark-detail-label">Описание</label>
              <textarea
                class="viewer-remark-detail-note"
                :value="selectedRemark.description"
                rows="3"
                placeholder="Текст замечания для согласования…"
                @input="updateSelectedRemarkDescription(($event.target as HTMLTextAreaElement).value)"
              />
            </div>
            <button
              v-if="selectedRemarkId"
              type="button"
              class="viewer-remarks-btn viewer-remarks-btn--danger"
              @click="deleteSelectedRemark"
            >
              Удалить выбранное
            </button>
          </template>
        </div>
        <div v-show="leftSidebarTab === 'layers'" class="viewer-left-sidebar-pane viewer-sidebar-panel viewer-layers-panel">
          <div class="viewer-models-header">
            <span class="viewer-models-title">Дерево слоёв</span>
            <button type="button" class="viewer-models-add" title="Новый слой" @click="addSceneLayer3d">+</button>
          </div>
          <div v-for="layer in sceneLayers3d" :key="layer.id" class="viewer-layer-row">
            <button type="button" class="viewer-component-item-eye-btn" @click="toggleSceneLayerVisibility(layer.id)">
              {{ layer.visible ? '👁' : '🚫' }}
            </button>
            <span class="viewer-layer-swatch" :style="{ background: layer.color }"></span>
            <span class="viewer-layer-name">{{ layer.name }}</span>
          </div>
          <p class="viewer-models-hint">Слой управляет видимостью назначенных деталей. Назначение — вкладка Параметры → Выделение.</p>
        </div>
        <div v-show="leftSidebarTab === 'library'" class="viewer-left-sidebar-pane viewer-sidebar-panel viewer-library-panel">
          <div class="viewer-models-header">
            <span class="viewer-models-title">Библиотека</span>
            <button type="button" class="viewer-models-add" title="Добавить модель" @click="openFileDialog">+</button>
          </div>
          <div v-if="libraryModels.length === 0" class="viewer-models-empty">Модели вне сцены появятся здесь (лимит {{ MAX_MODELS_IN_SCENE }} в сцене).</div>
          <div v-for="item in libraryModels" :key="item.id" class="viewer-library-item">
            <span class="viewer-model-accordion-name" :title="item.name">{{ item.name }}</span>
            <button type="button" class="viewer-models-btn viewer-models-btn-add" title="Добавить в сцену" @click="setModelInScene(item.id, true)">⊕</button>
            <button type="button" class="viewer-models-btn viewer-models-btn-remove" title="Удалить" @click="removeModel(item.id)">×</button>
          </div>
        </div>
      </div>
      <div class="viewer-main">
        <div ref="containerRef" class="viewer-container" />
        <div
          v-if="boxSelectRect"
          class="viewer-box-select-rect"
          :class="boxSelectRect.mode === 'window' ? 'viewer-box-select-rect--window' : 'viewer-box-select-rect--crossing'"
          :style="{ left: `${boxSelectRect.left}px`, top: `${boxSelectRect.top}px`, width: `${boxSelectRect.width}px`, height: `${boxSelectRect.height}px` }"
        />
        <Model3dScreenLayerOverlay
          v-if="selectedRemark && isRemarksPanelActive"
          ref="screenLayerOverlayRef"
          :shapes="selectedRemarkScreenShapes"
          :images="selectedRemarkScreenImages"
          :tool="remarkScreenTool"
          :color="remarkScreenColor"
          :visible="remarkScreenLayerVisible"
          :editable="remarkScreenLayerEditable"
          :selected-shape-id="remarkScreenSelectedShapeId"
          :selected-image-id="remarkScreenSelectedImageId"
          @update:shapes="onRemarkScreenShapesUpdate"
          @update:images="onRemarkScreenImagesUpdate"
          @update:selected-shape-id="remarkScreenSelectedShapeId = $event"
          @update:selected-image-id="remarkScreenSelectedImageId = $event"
          @update:tool="remarkScreenTool = $event"
          @change="markRemarksChanged"
        />
        <div
          v-if="partContextMenuOpen"
          class="viewer-part-context-menu"
          :style="{ left: `${partContextMenuX}px`, top: `${partContextMenuY}px` }"
        >
          <button
            v-if="contextMenuTargetModelId"
            type="button"
            class="viewer-part-context-menu-item"
            @click="togglePinFromContextMenu"
          >
            {{ contextMenuTargetModelId && pinnedByModelId[contextMenuTargetModelId] ? 'Открепить модель' : 'Закрепить модель' }}
          </button>
          <button
            v-if="contextMenuTargetIsHidden"
            type="button"
            class="viewer-part-context-menu-item"
            @click="showSelectedPartFromContextMenu"
          >
            Показать деталь
          </button>
          <button
            v-else
            type="button"
            class="viewer-part-context-menu-item"
            @click="hideSelectedPartFromContextMenu"
          >
            Скрыть деталь
          </button>
          <template v-if="contextMenuTargetModelId && contextMenuTargetPart">
            <div class="viewer-part-context-menu-label">Прозрачность</div>
            <div class="viewer-part-context-menu-opacity-row">
              <button
                type="button"
                class="viewer-part-context-menu-opacity-btn"
                title="Только выбранная геометрия под курсором"
                @click="setContextMenuOpacity(1, 'mesh')"
              >
                100%
              </button>
              <button type="button" class="viewer-part-context-menu-opacity-btn" @click="setContextMenuOpacity(0.75, 'mesh')">75%</button>
              <button type="button" class="viewer-part-context-menu-opacity-btn" @click="setContextMenuOpacity(0.5, 'mesh')">50%</button>
              <button type="button" class="viewer-part-context-menu-opacity-btn" @click="setContextMenuOpacity(0.25, 'mesh')">25%</button>
              <button type="button" class="viewer-part-context-menu-opacity-btn" @click="setContextMenuOpacity(0.1, 'mesh')">10%</button>
            </div>
            <button type="button" class="viewer-part-context-menu-item" @click="setContextMenuOpacity(0.5, 'row')">
              50% — одно имя в дереве (все экз.)
            </button>
            <button type="button" class="viewer-part-context-menu-item" @click="setContextMenuOpacity(0.5, 'model')">
              50% — вся сборка
            </button>
            <button type="button" class="viewer-part-context-menu-item" @click="resetContextMenuOpacity('mesh')">
              Сбросить прозрачность — деталь
            </button>
            <button type="button" class="viewer-part-context-menu-item" @click="resetContextMenuOpacity('model')">
              Сбросить прозрачность — вся сборка
            </button>
          </template>
        </div>
        <div v-if="isLoading" class="loading-overlay">
          <span class="loading-text">Загрузка модели…</span>
        </div>
      </div>
    </div>

    <div v-if="settingsModalOpen" class="viewer-settings-backdrop" @click.self="closeSettingsModal">
      <div class="viewer-settings-modal" role="dialog" aria-labelledby="viewer-settings-title">
        <div class="viewer-settings-head">
          <h2 id="viewer-settings-title">Настройки 3D</h2>
          <button type="button" class="viewer-settings-close" title="Закрыть" @click="closeSettingsModal">×</button>
        </div>
        <div class="viewer-settings-body">
          <section class="viewer-settings-section">
            <h3>Мышь и навигация</h3>
            <label class="viewer-settings-row">
              <span>Макс. отдаление</span>
              <input v-model.number="mouseMaxDistance" type="number" min="1000" max="500000" step="1000" class="viewer-mouse-input" @change="autoNavLimitsEnabled = false; applyMouseSettings()" />
            </label>
            <label class="viewer-settings-row">
              <span>Мин. приближение</span>
              <input v-model.number="mouseMinDistance" type="number" min="1" max="500" class="viewer-mouse-input" @change="autoNavLimitsEnabled = false; applyMouseSettings()" />
            </label>
            <label class="viewer-settings-row viewer-settings-row-check">
              <span>Автолимиты навигации</span>
              <input v-model="autoNavLimitsEnabled" type="checkbox" @change="onAutoNavLimitsChange" />
            </label>
            <label class="viewer-settings-row">
              <span>Скорость зума</span>
              <input v-model.number="mouseZoomSpeed" type="number" min="0.01" max="0.09" step="0.005" class="viewer-mouse-input" @change="applyMouseSettings()" />
            </label>
            <label class="viewer-settings-row viewer-settings-row-check">
              <span>Колёсико: к себе = отдаление</span>
              <input v-model="mouseInvertWheel" type="checkbox" />
            </label>
            <label class="viewer-settings-row">
              <span>Скорость вращения</span>
              <input v-model.number="mouseRotateSpeed" type="number" min="2.2" max="8.8" step="0.5" class="viewer-mouse-input" @change="applyMouseSettings()" />
            </label>
            <label class="viewer-settings-row">
              <span>Скорость панорамирования</span>
              <input v-model.number="mousePanSpeed" type="number" min="0.7" max="3.5" step="0.5" class="viewer-mouse-input" @change="applyMouseSettings()" />
            </label>
          </section>
          <section class="viewer-settings-section">
            <h3>Цвет и освещение</h3>
            <label class="viewer-settings-row">
              <span>Фон сцены</span>
              <input type="color" :value="sceneBackgroundHex" class="viewer-settings-color" @input="onSceneBackgroundInput" />
            </label>
            <label class="viewer-settings-row">
              <span>Насыщенность цветов деталей</span>
              <input
                type="range"
                :min="COLOR_VIVIDNESS_MIN"
                :max="COLOR_VIVIDNESS_MAX"
                :step="COLOR_VIVIDNESS_STEP"
                :value="colorVividness"
                @input="onColorVividnessInput"
              />
            </label>
            <label class="viewer-settings-row">
              <span>Яркость тона</span>
              <input type="range" :min="TINT_BRIGHTNESS_MIN" :max="TINT_BRIGHTNESS_MAX" :step="TINT_BRIGHTNESS_STEP" :value="tintBrightness" @input="onTintBrightnessInput" />
            </label>
            <label class="viewer-settings-row">
              <span>Режим света</span>
              <select class="viewer-scene-select" :value="shadingMode" @change="onShadingModeChange">
                <option value="lit">Обычный</option>
                <option value="unlit">Светлый</option>
              </select>
            </label>
            <label class="viewer-settings-row">
              <span>Пресет</span>
              <select class="viewer-scene-select" :value="lightPreset" @change="onLightPresetChange">
                <option value="engineering">Инженерный</option>
                <option value="soft">Мягкий</option>
              </select>
            </label>
            <label class="viewer-settings-row viewer-settings-row-check">
              <span>Доп. заполняющий свет (3 источника)</span>
              <input v-model="extraFillLightsEnabled" type="checkbox" @change="onExtraLightsChange" />
            </label>
            <label class="viewer-settings-row viewer-settings-row-check">
              <span>Контровой свет (2 источника)</span>
              <input v-model="extraRimLightsEnabled" type="checkbox" @change="onExtraLightsChange" />
            </label>
          </section>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.viewer-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  position: relative;
}
.viewer-3d-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.4rem 0.6rem;
  background: #141414;
  border-bottom: 1px solid #333;
  flex-wrap: wrap;
}
.viewer-3d-title {
  font-weight: 600;
  color: #fff;
  flex-shrink: 0;
}
.viewer-3d-btn-open-model {
  flex-shrink: 0;
  height: 30px;
  padding: 0 12px;
  font-size: 0.8rem;
  border-radius: 6px;
  border: 1px solid rgba(109, 143, 208, 0.55);
  background: linear-gradient(180deg, rgba(55, 78, 120, 0.95), rgba(40, 55, 88, 0.98));
  color: #eef4ff;
  cursor: pointer;
}
.viewer-3d-btn.viewer-3d-btn-open-model:hover {
  border-color: rgba(140, 170, 230, 0.85);
  background: linear-gradient(180deg, rgba(65, 92, 145, 0.98), rgba(48, 65, 105, 1));
}
.viewer-header-tabs {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
}
.viewer-header-tabs button {
  height: 28px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: rgba(27, 35, 50, 0.9);
  color: #d7e4ff;
  padding: 0 10px;
  font-size: 0.74rem;
  cursor: pointer;
}
.viewer-header-tabs button.active {
  border-color: #6d8fd0;
  background: rgba(65, 93, 150, 0.9);
}
.viewer-3d-tools {
  flex: 1 1 220px;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0;
  flex-wrap: wrap;
}
.viewer-header-block {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
  padding: 0.9rem 0.5rem 0.25rem;
  margin: 0 0.15rem;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.08);
  position: relative;
}
.viewer-measure-select {
  height: 30px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(33, 45, 68, 0.95);
  color: #e8f0ff;
  padding: 0 8px;
  font-size: 0.72rem;
  min-width: 148px;
}
.viewer-header-block[data-group]::before {
  content: attr(data-group);
  position: absolute;
  top: 0.15rem;
  left: 0.45rem;
  font-size: 0.62rem;
  letter-spacing: 0.03em;
  color: #8da2c9;
  text-transform: uppercase;
}
.viewer-header-block:first-of-type {
  margin-left: 0;
}
.viewer-header-block-frame {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}
.viewer-explode-control .viewer-frame-opacity-input {
  min-width: 3.6rem;
}

.viewer-frame-opacity-input {
  width: 2.8rem;
  padding: 0.2rem 0.25rem;
  font-size: 0.75rem;
  color: #e0e0e0;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 4px;
  text-align: center;
}
.viewer-frame-opacity-input::-webkit-inner-spin-button {
  opacity: 1;
}
.viewer-explode-control {
  flex-wrap: wrap;
  gap: 4px 8px;
  max-width: 280px;
}
.viewer-explode-reset {
  min-width: 28px;
  padding: 2px 6px;
}
.viewer-tree-explode {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 8px;
  margin: 6px 8px 8px;
  padding: 6px 8px;
  font-size: 12px;
  color: var(--viewer-muted, #9aa8bc);
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
}
.viewer-tree-explode-slider {
  flex: 1;
  min-width: 80px;
  accent-color: #6a9fd8;
}
.viewer-explode-mm-hint {
  font-size: 0.75rem;
  opacity: 0.85;
  white-space: nowrap;
  min-width: 4.5em;
}

.viewer-tree-explode-val {
  min-width: 1.5rem;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.viewer-frame-opacity-slider {
  width: 4rem;
  vertical-align: middle;
}
.viewer-part-colors-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.74rem;
  color: #b8c5da;
  margin-left: 0.15rem;
}
.viewer-part-colors-toggle input {
  width: 0.95rem;
  height: 0.95rem;
  accent-color: #6a8bc7;
}
.viewer-3d-btn {
  padding: 0.3rem 0.55rem;
  font-size: 0.82rem;
  border-radius: 4px;
  cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #e0e0e0;
  background: rgba(80, 110, 150, 0.5);
}
.viewer-3d-btn:hover {
  background: rgba(100, 130, 180, 0.6);
}
.viewer-3d-btn.active {
  background: #4a6fc7;
  border-color: #5a7fd7;
}
.viewer-3d-btn.btn-fix {
  width: 2rem;
  color: #0a0;
  background: rgba(40, 120, 60, 0.6);
}
.viewer-3d-btn.btn-clear {
  width: 2rem;
  color: #c00;
  background: rgba(120, 40, 40, 0.6);
}
.viewer-orientation-dropdown {
  position: relative;
}
.viewer-orient-trigger {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.viewer-orient-trigger.open {
  background: rgba(100, 130, 180, 0.6);
}
.viewer-orient-trigger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.viewer-orient-cube {
  flex-shrink: 0;
}
.viewer-orientation-menu {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 0.2rem;
  min-width: 160px;
  background: #252525;
  border: 1px solid #444;
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
  padding: 0.3rem;
  z-index: 100;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.viewer-orient-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.6rem;
  font-size: 0.85rem;
  color: #e0e0e0;
  background: transparent;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  text-align: left;
  width: 100%;
}
.viewer-orient-item:hover {
  background: rgba(80, 110, 150, 0.5);
}
.viewer-orient-cube-icon {
  flex-shrink: 0;
}
.viewer-orient-label {
  flex: 1;
}
.viewer-orient-text-only {
  padding-left: 0.25rem;
}
.viewer-orient-fade-enter-active,
.viewer-orient-fade-leave-active {
  transition: opacity 0.15s ease;
}
.viewer-orient-fade-enter-from,
.viewer-orient-fade-leave-to {
  opacity: 0;
}
.viewer-mouse-dropdown {
  /* same as orientation dropdown */
}
.viewer-mouse-menu {
  min-width: 260px;
  padding: 0.5rem;
}
.viewer-mouse-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.25rem 0;
}
.viewer-mouse-row-check {
  align-items: center;
}
.viewer-mouse-label {
  font-size: 0.78rem;
  color: #b0b8c8;
  flex: 1;
  min-width: 0;
}
.viewer-mouse-input {
  width: 5rem;
  padding: 0.2rem 0.35rem;
  font-size: 0.8rem;
  background: rgba(0, 0, 0, 0.35);
  color: #e0e0e0;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 4px;
}
.viewer-mouse-check {
  width: 1rem;
  height: 1rem;
  accent-color: #6a8bc7;
}
.viewer-3d-offset {
  width: 4rem;
  padding: 0.25rem 0.35rem;
  font-size: 0.8rem;
  background: rgba(0, 0, 0, 0.3);
  color: #e0e0e0;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 4px;
}
.viewer-3d-slider {
  width: 5rem;
  vertical-align: middle;
}
.viewer-3d-select {
  padding: 0.25rem 0.4rem;
  font-size: 0.78rem;
  background: rgba(0, 0, 0, 0.3);
  color: #e0e0e0;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 4px;
  cursor: pointer;
}
.viewer-body {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
}
.viewer-left-sidebar {
  flex-shrink: 0;
  width: 220px;
  min-width: 180px;
  max-width: 320px;
  background: #1e2433;
  border-right: 1px solid #3a4a6a;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.viewer-left-sidebar-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.2rem;
  padding: 0.35rem 0.35rem 0.25rem;
  border-bottom: 1px solid #3a4a6a;
  flex-shrink: 0;
}
.viewer-left-tab {
  flex: 1 1 45%;
  min-width: 0;
  padding: 0.28rem 0.35rem;
  font-size: 0.68rem;
  border: 1px solid #3d4d68;
  border-radius: 4px;
  background: #252f42;
  color: #b8c8e0;
  cursor: pointer;
}
.viewer-left-tab.active {
  background: #395f96;
  border-color: #5d83c7;
  color: #f0f5ff;
}
.viewer-left-sidebar-tabs--kompas .viewer-left-tab {
  flex: 1 1 22%;
  font-size: 0.85rem;
  padding: 0.4rem 0.2rem;
  display: flex;
  align-items: center;
  justify-content: center;
}
.viewer-params-subtabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.15rem;
  padding: 0.25rem 0.35rem;
  border-bottom: 1px solid #3a4a6a;
  flex-shrink: 0;
}
.viewer-params-subtab {
  flex: 1 1 auto;
  font-size: 0.62rem;
  padding: 0.2rem 0.25rem;
  border: 1px solid #3d4d68;
  border-radius: 3px;
  background: #1e2636;
  color: #9eb4d8;
  cursor: pointer;
}
.viewer-params-subtab.active {
  background: #334a72;
  color: #eef4ff;
}
.viewer-component-item-category {
  font-weight: 600;
  color: #a8bdd8;
}
.viewer-component-item-label--category {
  font-weight: 600;
  color: #c5d4ef;
}
.viewer-component-item-chevron {
  width: 0.85rem;
  font-size: 0.55rem;
  color: #8fa3c4;
  flex-shrink: 0;
}
.viewer-box-select-rect {
  position: absolute;
  pointer-events: none;
  border-width: 1px;
  border-style: solid;
  z-index: 12;
  box-sizing: border-box;
}
.viewer-box-select-rect--window {
  border-color: #4a8cff;
  background: rgba(74, 140, 255, 0.12);
}
.viewer-box-select-rect--crossing {
  border-color: #44cc66;
  background: rgba(68, 204, 102, 0.12);
}
.viewer-selection-panel .viewer-selection-header {
  font-size: 0.75rem;
  font-weight: 600;
  color: #d7e4ff;
  margin-bottom: 0.35rem;
}
.viewer-selection-summary {
  font-size: 0.68rem;
  color: #9eb4d8;
  margin: 0 0 0.35rem;
}
.viewer-selection-mode-btn {
  width: 100%;
  margin-bottom: 0.35rem;
}
.viewer-selection-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem;
  margin-bottom: 0.35rem;
  font-size: 0.68rem;
  color: #9eb4d8;
}
.viewer-selection-color {
  width: 2.2rem;
  height: 1.6rem;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
}
.viewer-layer-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.25rem 0.35rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.viewer-layer-swatch {
  width: 0.75rem;
  height: 0.75rem;
  border-radius: 2px;
  border: 1px solid rgba(255, 255, 255, 0.25);
}
.viewer-layer-name {
  font-size: 0.72rem;
  color: #d7e4ff;
}
.viewer-library-item {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.3rem 0.35rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.viewer-main {
  position: relative;
}
.viewer-left-sidebar-pane {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.viewer-sidebar-panel {
  overflow: auto;
  padding: 0.35rem 0.4rem 0.5rem;
}
.viewer-assembly-body--sidebar {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.viewer-measurements-sidebar .viewer-measurements-controls {
  padding: 0 0.1rem;
}
.viewer-remarks-panel {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}
.viewer-remarks-hint {
  margin: 0;
  font-size: 0.72rem;
  color: #9eb0c8;
  line-height: 1.35;
}
.viewer-remarks-view-hint {
  margin: 0;
  font-size: 0.68rem;
  color: #d4a574;
  line-height: 1.3;
}
.viewer-remarks-nav-hint {
  margin: 0;
  font-size: 0.65rem;
  color: #8ea2c2;
  line-height: 1.3;
}
.viewer-remarks-markup-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  align-items: center;
}
.viewer-remarks-markup-btn {
  padding: 0.22rem 0.4rem;
  font-size: 0.68rem;
  border: 1px solid #3a4a6a;
  border-radius: 3px;
  background: #2a3548;
  color: #c7d6ee;
  cursor: pointer;
}
.viewer-remarks-markup-btn.active {
  background: #395f96;
  border-color: #6d8fd0;
}
.viewer-remarks-markup-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.viewer-remarks-markup-btn--danger {
  border-color: #6a4040;
  color: #f0c8c8;
}
.viewer-remarks-color {
  width: 28px;
  height: 24px;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
}
.viewer-remarks-model {
  margin: 0;
  font-size: 0.7rem;
  color: #b8c8e8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.viewer-remarks-empty {
  margin: 0;
  font-size: 0.72rem;
  color: #7a8ea8;
}
.viewer-remarks-filter-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.viewer-remarks-filter-label,
.viewer-remark-detail-label {
  font-size: 0.68rem;
  color: #8ea2c2;
}
.viewer-remarks-filter-select {
  flex: 1;
  font-size: 0.72rem;
  padding: 0.2rem 0.3rem;
  border: 1px solid #3a4a6a;
  border-radius: 4px;
  background: #252d38;
  color: #c7d6ee;
}
.viewer-remark-detail {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding-top: 0.35rem;
  border-top: 1px solid #3a4a6a;
}
.viewer-remark-detail-note {
  width: 100%;
  box-sizing: border-box;
  font-size: 0.72rem;
  padding: 0.3rem;
  border: 1px solid #3a4a6a;
  border-radius: 4px;
  background: #1e2838;
  color: #dce8f8;
  resize: vertical;
  min-height: 3.5rem;
}
.viewer-remarks-item-head {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  min-width: 0;
}
.viewer-remarks-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}
.viewer-remarks-btn {
  padding: 0.35rem 0.5rem;
  font-size: 0.72rem;
  border: 1px solid #3a4a6a;
  border-radius: 4px;
  background: #2d3a52;
  color: #b8c8e0;
  cursor: pointer;
}
.viewer-remarks-btn--primary {
  border-color: #4a6a4a;
  background: #2a3d2a;
  color: #c8e8c8;
}
.viewer-remarks-btn--block {
  width: 100%;
}
.viewer-remarks-btn--danger {
  border-color: #6a4040;
  color: #f0c8c8;
}
.viewer-remarks-btn:hover:not(:disabled) {
  filter: brightness(1.08);
}
.viewer-remarks-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.viewer-remarks-item {
  display: flex;
  align-items: stretch;
  gap: 0.2rem;
  border-radius: 4px;
  border: 1px solid transparent;
}
.viewer-remarks-item.active {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.12);
}
.viewer-remarks-item-btn {
  flex: 1;
  min-width: 0;
  text-align: left;
  padding: 0.35rem 0.4rem;
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.viewer-remarks-item-title {
  font-size: 0.78rem;
  color: #e0e8f4;
}
.viewer-remarks-item-meta {
  font-size: 0.65rem;
  color: #8ea4c7;
}
.viewer-remarks-item-del {
  flex-shrink: 0;
  align-self: center;
  width: 22px;
  height: 22px;
  margin-right: 0.15rem;
  border: 1px solid #5b6f90;
  border-radius: 4px;
  background: rgba(70, 80, 110, 0.9);
  color: #dce8f8;
  cursor: pointer;
  line-height: 1;
  padding: 0;
  font-size: 0.95rem;
}
.viewer-remarks-item-del:hover {
  background: rgba(173, 66, 66, 0.95);
  border-color: #b35f5f;
}
.viewer-models-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.4rem 0.5rem;
  font-size: 0.85rem;
  border-bottom: 1px solid #3a4a6a;
}
.viewer-models-title {
  font-weight: 600;
  color: #e0e8f0;
}
.viewer-models-count {
  color: #8a9bb5;
}
.viewer-models-add {
  margin-left: auto;
  width: 24px;
  height: 24px;
  padding: 0;
  font-size: 1.1rem;
  line-height: 1;
  background: #3d4a62;
  color: #e0e8f0;
  border: 1px solid #4a5f7a;
  border-radius: 4px;
  cursor: pointer;
}
.viewer-models-add:hover {
  background: #4a6fc7;
}
.viewer-models-empty {
  flex: 1;
  padding: 0.5rem;
  font-size: 0.75rem;
  color: #6a7a8a;
  overflow-y: auto;
}
.viewer-tree-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  margin: 0 0.35rem 0.35rem;
}
.viewer-tree-isolate-check {
  display: flex;
  align-items: flex-start;
  gap: 0.35rem;
  margin: 0 0.35rem 0.35rem;
  font-size: 0.62rem;
  color: #9eb4d8;
  line-height: 1.35;
  cursor: pointer;
}
.viewer-models-hint {
  font-size: 0.64rem;
  color: #8fa3c4;
  padding: 0 0.45rem 0.35rem;
  line-height: 1.35;
}
.viewer-placement-panel {
  margin: 0 0.35rem 0.5rem;
  padding: 0.45rem 0.5rem;
  border: 1px solid #4a6a9a;
  border-radius: 6px;
  background: rgba(35, 50, 78, 0.95);
}
.viewer-placement-title {
  font-size: 0.72rem;
  font-weight: 600;
  color: #c8daf8;
  margin-bottom: 0.25rem;
}
.viewer-placement-hint {
  font-size: 0.62rem;
  color: #9eb4d8;
  margin: 0 0 0.35rem;
  line-height: 1.35;
}
.viewer-placement-coords {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.25rem;
  margin-bottom: 0.35rem;
}
.viewer-placement-field {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  font-size: 0.62rem;
  color: #8fa3c4;
}
.viewer-placement-input {
  width: 100%;
  box-sizing: border-box;
  height: 26px;
  border-radius: 4px;
  border: 1px solid #3a4a6a;
  background: rgba(20, 28, 42, 0.95);
  color: #e8f0ff;
  padding: 0 4px;
  font-size: 0.72rem;
}
.viewer-placement-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}
.viewer-placement-btn {
  flex: 1 1 auto;
  min-width: 4.5rem;
  height: 26px;
  border-radius: 4px;
  border: 1px solid #3a4a6a;
  background: rgba(40, 52, 72, 0.95);
  color: #d7e4ff;
  font-size: 0.68rem;
  cursor: pointer;
}
.viewer-placement-btn-primary {
  border-color: #6d8fd0;
  background: rgba(65, 93, 150, 0.9);
}
.viewer-models-metrics {
  margin: 0.1rem 0.2rem 0.4rem;
  padding: 0.3rem 0.4rem;
  border: 1px solid #3a4a6a;
  border-radius: 6px;
  background: rgba(30, 36, 51, 0.9);
  color: #b7c7db;
  font-size: 0.72rem;
  line-height: 1.3;
}
.viewer-measurements-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0.1rem 0.2rem 0.25rem;
  color: #c5d2e6;
  font-size: 0.72rem;
}
.viewer-measurements-float {
  position: absolute;
  width: clamp(220px, 30vw, 520px);
  min-width: 220px;
  max-width: 92vw;
  min-height: 220px;
  max-height: min(78vh, 640px);
  z-index: 1200;
  background: rgba(18, 24, 35, 0.95);
  border: 1px solid #4a5f7a;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  overflow: auto;
  resize: both;
}
.viewer-measurements-float-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  background: rgba(39, 56, 84, 0.95);
  color: #dce8f8;
  font-size: 0.76rem;
  cursor: move;
}
.viewer-measurements-clear {
  border: 1px solid #4a5f7a;
  background: #2d3a52;
  color: #d7e1ef;
  border-radius: 4px;
  font-size: 0.68rem;
  padding: 2px 6px;
  cursor: pointer;
}
.viewer-measurements-clear:hover {
  background: #3a4f70;
}
.viewer-measurements-empty {
  margin: 0.25rem 0.35rem 0.4rem;
  color: #6f8098;
  font-size: 0.72rem;
}
.viewer-measurements-controls {
  display: grid;
  grid-template-columns: 1fr;
  gap: 6px;
  margin: 0.25rem 0.2rem 0.35rem;
}
.viewer-measurements-select {
  width: 100%;
  height: 28px;
  border-radius: 5px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(40, 52, 78, 0.92);
  color: #ecf2ff;
  padding: 0 8px;
  font-size: 0.7rem;
}
.viewer-measurements-dim-row {
  display: grid;
  grid-template-columns: 44px 1fr 44px 1fr;
  gap: 6px;
  align-items: center;
  color: #9db2cf;
  font-size: 0.66rem;
}
.viewer-measurements-dim-input {
  width: 100%;
  height: 24px;
  border-radius: 5px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(40, 52, 78, 0.92);
  color: #ecf2ff;
  padding: 0 6px;
  font-size: 0.68rem;
}
.viewer-measurements-cad-row {
  display: grid;
  grid-template-columns: 1fr;
  gap: 4px;
}
.viewer-measurements-cad-row > label {
  font-size: 0.66rem;
  color: #9db2cf;
}
.viewer-measurements-cad-pick {
  display: flex;
  gap: 6px;
}
.viewer-measurements-cad-input {
  flex: 1;
  height: 26px;
  border-radius: 5px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(40, 52, 78, 0.92);
  color: #ecf2ff;
  padding: 0 7px;
  font-size: 0.68rem;
  cursor: pointer;
}
.viewer-measurements-cad-btn {
  height: 26px;
  border-radius: 5px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(86, 122, 194, 0.9);
  color: #fff;
  padding: 0 8px;
  font-size: 0.66rem;
  cursor: pointer;
}
.viewer-measurements-cad-btn:hover {
  background: rgba(105, 143, 218, 0.95);
}
.viewer-measurements-cad-status {
  font-size: 0.66rem;
  color: #dce8ff;
  border: 1px solid rgba(125, 155, 220, 0.25);
  background: rgba(26, 38, 58, 0.8);
  border-radius: 5px;
  padding: 3px 6px;
}
.viewer-measurements-hint {
  margin: 0;
  font-size: 0.68rem;
  color: #b8cce8;
  line-height: 1.4;
  padding: 6px 8px;
  background: rgba(26, 38, 58, 0.75);
  border-radius: 5px;
  border-left: 3px solid rgba(127, 194, 255, 0.65);
}
.viewer-measurements-cad-pick--optional {
  opacity: 0.82;
}
.viewer-measurements-cad-new {
  height: 26px;
  border-radius: 5px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(76, 114, 190, 0.9);
  color: #fff;
  font-size: 0.68rem;
  cursor: pointer;
}
.viewer-measurements-cad-new:hover {
  background: rgba(95, 132, 210, 0.95);
}
.viewer-measurements-cad-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.viewer-measurements-cad-item {
  height: 24px;
  border-radius: 5px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: rgba(39, 52, 78, 0.92);
  color: #e7efff;
  padding: 0 7px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.66rem;
  cursor: pointer;
}
.viewer-measurements-cad-detail {
  border: 1px solid rgba(125, 155, 220, 0.22);
  background: rgba(23, 34, 54, 0.82);
  border-radius: 5px;
  padding: 5px 7px;
  font-size: 0.64rem;
  color: #c8d7f3;
  display: grid;
  gap: 3px;
}
.viewer-measurements-cad-detail-btn {
  justify-self: start;
  height: 22px;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(71, 104, 170, 0.9);
  color: #fff;
  padding: 0 7px;
  font-size: 0.62rem;
  cursor: pointer;
}
.viewer-measurements-list {
  max-height: 270px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin: 0 0.2rem 0.4rem;
}
.viewer-measurements-table-head {
  display: grid;
  grid-template-columns: 34px 40px 64px 64px 1fr 24px;
  gap: 6px;
  align-items: center;
  font-size: 0.64rem;
  color: #9db2cf;
  padding: 2px 6px 4px;
  border-bottom: 1px solid rgba(90, 110, 140, 0.35);
}
.viewer-measurements-row {
  display: grid;
  grid-template-columns: 34px 44px 1fr 24px;
  gap: 6px;
  align-items: center;
  border: 1px solid #3a4a6a;
  background: rgba(32, 40, 58, 0.9);
  color: #d7e1ef;
  border-radius: 6px;
  padding: 5px 6px;
  cursor: pointer;
  font-size: 0.72rem;
}
.viewer-measurements-row:hover {
  background: rgba(48, 63, 92, 0.95);
}
.viewer-measurements-row.active {
  border-color: #6d8fd0;
  box-shadow: inset 0 0 0 1px rgba(109, 143, 208, 0.35);
}
.viewer-measurements-cell-id {
  color: #9db2cf;
  font-size: 0.68rem;
}
.viewer-measurements-cell-value {
  text-align: right;
  font-variant-numeric: tabular-nums;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.viewer-measurements-row-perp {
  font-size: 0.78rem;
  font-weight: 700;
  color: #9fe2ff;
}
.viewer-measurements-row-del {
  width: 20px;
  height: 20px;
  border: 1px solid #5b6f90;
  border-radius: 4px;
  background: rgba(70, 80, 110, 0.9);
  color: #dce8f8;
  cursor: pointer;
  line-height: 1;
  padding: 0;
}
.viewer-measurements-row-del:hover {
  background: rgba(173, 66, 66, 0.95);
  border-color: #b35f5f;
}
.viewer-assembly-panel {
  position: absolute;
  left: 330px;
  top: 56px;
  z-index: 12;
  width: clamp(220px, 24vw, 360px);
  min-width: 220px;
  max-width: 92vw;
  min-height: 56px;
  max-height: 80vh;
  background: rgba(18, 24, 35, 0.95);
  border: 1px solid rgba(115, 145, 200, 0.4);
  border-radius: 8px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
  color: #e7efff;
  resize: both;
  overflow: auto;
}
.viewer-assembly-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  border-bottom: 1px solid rgba(115, 145, 200, 0.22);
  font-size: 0.8rem;
  font-weight: 600;
  cursor: move;
  user-select: none;
}
.viewer-assembly-toggle {
  width: 24px;
  height: 24px;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(80, 110, 160, 0.45);
  color: #e6eefb;
  cursor: pointer;
}
.viewer-assembly-body {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.viewer-assembly-row {
  display: grid;
  grid-template-columns: 1fr 1.2fr;
  align-items: center;
  gap: 6px;
  font-size: 0.72rem;
}
.viewer-assembly-select,
.viewer-assembly-input {
  width: 100%;
  height: 28px;
  border-radius: 5px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: rgba(40, 52, 78, 0.92);
  color: #ecf2ff;
  padding: 0 7px;
  font-size: 0.72rem;
}
.viewer-assembly-pick {
  display: flex;
  gap: 6px;
  align-items: center;
}
.viewer-assembly-input-pick {
  cursor: pointer;
}
.viewer-assembly-pick-btn {
  height: 28px;
  border-radius: 5px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(86, 122, 194, 0.9);
  color: #fff;
  padding: 0 9px;
  font-size: 0.7rem;
  cursor: pointer;
  white-space: nowrap;
}
.viewer-assembly-pick-btn:hover {
  background: rgba(105, 143, 218, 0.95);
}
.viewer-assembly-apply {
  margin-top: 2px;
  height: 30px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(76, 114, 190, 0.9);
  color: #fff;
  cursor: pointer;
  font-size: 0.76rem;
  font-weight: 600;
}
.viewer-assembly-apply:hover {
  background: rgba(92, 132, 214, 0.95);
}
.viewer-assembly-note {
  font-size: 0.66rem;
  color: #a9bddf;
}
.viewer-assembly-note-coord {
  margin-top: -0.1rem;
  font-style: italic;
}
.viewer-assembly-row-check {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.7rem;
  color: #c8d4e8;
  margin: 0.15rem 0 0.25rem;
  cursor: pointer;
}
.viewer-assembly-row-check input {
  flex-shrink: 0;
}
.viewer-assembly-world-csys {
  margin: 0.5rem 0 0.35rem;
  border: 1px solid rgba(100, 140, 200, 0.35);
  border-radius: 6px;
  background: rgba(22, 30, 48, 0.65);
}
.viewer-assembly-world-csys-title {
  width: 100%;
  text-align: left;
  padding: 0.35rem 0.45rem;
  border: none;
  background: transparent;
  color: #c8daf8;
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
}
.viewer-assembly-world-csys-body {
  padding: 0 0.45rem 0.45rem;
}
.viewer-assembly-world-plane-btns {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  margin-top: 0.25rem;
}
.viewer-assembly-world-plane-btn {
  text-align: left;
  font-size: 0.66rem;
  padding: 0.25rem 0.35rem;
  border-radius: 4px;
  border: 1px solid rgba(120, 150, 200, 0.35);
  background: rgba(35, 48, 72, 0.9);
  color: #d0dcf0;
  cursor: pointer;
}
.viewer-assembly-world-plane-btn:hover {
  background: rgba(55, 78, 120, 0.95);
}
.viewer-assembly-world-plane-btn.active {
  border-color: rgba(120, 200, 255, 0.7);
  background: rgba(50, 90, 140, 0.95);
}
.viewer-assembly-status {
  font-size: 0.68rem;
  color: #dce8ff;
  background: rgba(26, 38, 58, 0.8);
  border: 1px solid rgba(125, 155, 220, 0.25);
  border-radius: 5px;
  padding: 4px 6px;
}
.viewer-assembly-mates {
  margin-top: 6px;
  border-top: 1px solid rgba(125, 155, 220, 0.2);
  padding-top: 6px;
}
.viewer-assembly-mates-title {
  font-size: 0.7rem;
  font-weight: 600;
  color: #c8daf8;
  margin-bottom: 4px;
}
.viewer-assembly-mate-row {
  display: grid;
  grid-template-columns: 2rem 1fr 1.6rem;
  align-items: center;
  gap: 4px;
  font-size: 0.68rem;
  padding: 3px 6px;
  margin: 0 -4px;
  border-radius: 4px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  cursor: pointer;
  outline: none;
}
.viewer-assembly-mate-row:hover {
  background: rgba(125, 155, 220, 0.12);
}
.viewer-assembly-mate-row-active {
  background: rgba(80, 140, 255, 0.22);
  border-bottom-color: rgba(125, 155, 220, 0.2);
}
.viewer-assembly-mate-row-active:hover {
  background: rgba(80, 140, 255, 0.28);
}
.viewer-assembly-mate-no {
  color: #9db2cf;
}
.viewer-assembly-mate-type {
  color: #e8f0ff;
}
.viewer-assembly-mate-del {
  justify-self: end;
  width: 22px;
  height: 22px;
  padding: 0;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(150, 70, 70, 0.85);
  color: #fff;
  cursor: pointer;
  font-size: 0.85rem;
  line-height: 1;
}
.viewer-assembly-mate-del:hover {
  background: rgba(180, 60, 60, 0.95);
}
.viewer-models-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.4rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.viewer-model-accordion {
  flex: 1;
  overflow-y: auto;
  padding: 0.35rem 0.4rem 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.viewer-model-accordion-item {
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  background: rgba(30, 36, 48, 0.55);
}
.viewer-model-accordion-item.viewer-model-accordion-focused {
  border-color: rgba(120, 160, 230, 0.55);
}
.viewer-model-accordion-item.viewer-model-accordion-hidden {
  opacity: 0.72;
}
.viewer-model-accordion-header {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.35rem 0.4rem;
  cursor: pointer;
  user-select: none;
}
.viewer-model-accordion-header-active {
  background: rgba(70, 100, 150, 0.28);
}
.viewer-model-accordion-header:hover {
  background: rgba(70, 100, 150, 0.18);
}
.viewer-model-accordion-chevron {
  flex-shrink: 0;
  width: 1.2rem;
  height: 1.2rem;
  border: none;
  background: transparent;
  color: #a8b8d0;
  cursor: pointer;
  padding: 0;
  font-size: 0.62rem;
  line-height: 1;
}
.viewer-model-accordion-name {
  flex: 1;
  min-width: 0;
  font-size: 0.72rem;
  color: #dde6f4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.viewer-model-accordion-parts {
  padding: 0 0.35rem 0.35rem;
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
  max-height: 42vh;
  overflow-y: auto;
}
.viewer-model-accordion-parts .viewer-component-item {
  font-size: 0.68rem;
}
.viewer-model-accordion-header .viewer-models-btn {
  position: static;
  width: 1.35rem;
  height: 1.35rem;
  padding: 0;
  font-size: 0.85rem;
  line-height: 1;
}
.viewer-component-tree {
  margin: 0.25rem 0.4rem 0.4rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  padding-top: 0.45rem;
  max-height: 34vh;
  overflow-y: auto;
}
.viewer-component-tree-header {
  font-size: 0.74rem;
  color: #cfd7e7;
  margin-bottom: 0.25rem;
}
.viewer-component-model-group {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  margin-bottom: 0.35rem;
}
.viewer-component-model-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.7rem;
  color: #9fb0cb;
}
.viewer-component-item {
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(45, 58, 83, 0.45);
  color: #dde6f4;
  border-radius: 4px;
  font-size: 0.72rem;
  text-align: left;
  padding: 0.2rem 0.35rem;
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.viewer-component-item:hover {
  background: rgba(88, 116, 168, 0.45);
}
.viewer-component-item-selected {
  border-color: rgba(150, 190, 255, 0.55);
  background: rgba(82, 120, 186, 0.38);
}
.viewer-component-item-spacer {
  flex: 1;
}
.viewer-component-item-eye-btn {
  border: 1px solid rgba(255, 255, 255, 0.22);
  background: rgba(26, 34, 51, 0.9);
  color: #e2e9f5;
  border-radius: 4px;
  width: 1.35rem;
  height: 1.35rem;
  line-height: 1;
  padding: 0;
  cursor: pointer;
}
.viewer-component-item-eye-btn:hover {
  background: rgba(97, 128, 184, 0.65);
}
.viewer-component-item-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.viewer-models-card {
  flex-shrink: 0;
  position: relative;
  background: #252525;
  border: 1px solid #3a4a6a;
  border-radius: 6px;
  padding: 0.25rem;
  cursor: pointer;
}
.viewer-models-card-hidden {
  opacity: 0.7;
  border-style: dashed;
}
.viewer-models-card-hidden:hover {
  opacity: 1;
}
.viewer-models-thumb {
  display: block;
  width: 100%;
  aspect-ratio: 4/3;
  object-fit: contain;
  background: #1a1a1a;
  border-radius: 4px;
}
.viewer-models-name {
  display: block;
  font-size: 0.65rem;
  color: #a0b0c8;
  margin-top: 0.2rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.viewer-models-actions {
  position: absolute;
  bottom: 0.4rem;
  right: 0.4rem;
  display: flex;
  gap: 2px;
}
.viewer-models-btn {
  width: 20px;
  height: 20px;
  padding: 0;
  font-size: 0.9rem;
  line-height: 1;
  background: rgba(60, 80, 120, 0.9);
  color: #e0e8f0;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}
.viewer-models-btn:hover {
  background: #4a6fc7;
}
.viewer-models-btn-add {
  background: rgba(60, 140, 80, 0.9);
}
.viewer-models-btn-add:hover {
  background: #2d8a4a;
}
.viewer-models-btn-remove {
  background: rgba(180, 60, 60, 0.9);
}
.viewer-models-btn-remove:hover {
  background: #b43c3c;
}
.viewer-main {
  flex: 1;
  min-width: 0;
  position: relative;
}
.viewer-container {
  position: absolute;
  inset: 0;
}
.viewer-part-context-menu {
  position: absolute;
  z-index: 30;
  min-width: 9rem;
  background: rgba(24, 28, 40, 0.98);
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 6px;
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.45);
  padding: 0.3rem;
}
.viewer-part-context-menu-item {
  width: 100%;
  text-align: left;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #e3e9f5;
  padding: 0.35rem 0.45rem;
  font-size: 0.8rem;
  cursor: pointer;
}
.viewer-part-context-menu-item:hover {
  background: rgba(102, 129, 180, 0.35);
}
.viewer-part-context-menu-label {
  font-size: 0.72rem;
  color: #9aa8c0;
  padding: 0.35rem 0.45rem 0.15rem;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  margin-top: 0.2rem;
}
.viewer-part-context-menu-opacity-row {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  padding: 0 0.3rem 0.25rem;
}
.viewer-part-context-menu-opacity-btn {
  flex: 1 1 auto;
  min-width: 2.1rem;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 4px;
  background: rgba(40, 48, 64, 0.9);
  color: #e3e9f5;
  font-size: 0.72rem;
  padding: 0.28rem 0.2rem;
  cursor: pointer;
}
.viewer-part-context-menu-opacity-btn:hover {
  background: rgba(102, 129, 180, 0.35);
}
.viewer-scene-panel {
  position: absolute;
  top: 8px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10;
  background: rgba(30, 36, 51, 0.9);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 8px;
  padding: clamp(4px, 0.5vw, 6px) clamp(6px, 0.9vw, 10px);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
  overflow: visible;
  isolation: isolate;
  max-width: calc(100vw - 16px);
  width: max-content;
}
.viewer-scene-panel-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  flex-wrap: wrap;
  max-width: 100%;
}
.viewer-scene-group {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 0.85rem 4px 2px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(20, 24, 35, 0.45);
  position: relative;
}
.viewer-scene-group[data-group="Вид"] {
  order: 1;
}
.viewer-scene-group[data-group="Инструменты"] {
  order: 2;
}
.viewer-scene-group[data-group="Отображение"] {
  order: 3;
  flex-basis: 100%;
  justify-content: center;
}
@media (max-width: 1200px) {
  .viewer-scene-panel {
    max-width: calc(100vw - 10px);
  }
  .viewer-scene-group {
    gap: 4px;
    padding: 0.7rem 4px 2px;
  }
  .viewer-scene-group[data-group]::before {
    font-size: 0.54rem;
  }
  .viewer-scene-btn,
  .viewer-scene-toggle,
  .viewer-scene-select {
    height: 22px;
    font-size: 0.62rem;
  }
}
@media (max-width: 900px) {
  .viewer-measurements-float,
  .viewer-assembly-panel {
    min-width: 180px;
    width: clamp(180px, 44vw, 300px);
  }
  .viewer-scene-panel-row {
    gap: 3px;
  }
  .viewer-scene-group {
    padding: 0.62rem 3px 2px;
  }
  .viewer-scene-group[data-group]::before {
    left: 0.28rem;
    top: 0.1rem;
  }
  .viewer-scene-btn,
  .viewer-scene-toggle,
  .viewer-scene-select {
    height: 20px;
    font-size: 0.58rem;
  }
}
.viewer-scene-group[data-group]::before {
  content: attr(data-group);
  position: absolute;
  top: 0.12rem;
  left: 0.35rem;
  font-size: 0.58rem;
  letter-spacing: 0.03em;
  color: #9aaccf;
  text-transform: uppercase;
}
.viewer-scene-dropdown {
  position: relative;
}
.viewer-scene-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  background: rgba(60, 80, 120, 0.4);
  color: #e0e0e0;
  cursor: pointer;
}
.viewer-scene-btn:hover:not(:disabled) {
  background: rgba(80, 110, 160, 0.6);
}
.viewer-scene-btn.active,
.viewer-scene-btn.open {
  background: rgba(90, 130, 200, 0.7);
  border-color: rgba(255, 255, 255, 0.35);
}
.viewer-scene-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.viewer-scene-icon {
  flex-shrink: 0;
}
.viewer-scene-frame-block {
  display: flex;
  align-items: center;
  gap: 2px;
}
.viewer-scene-tint-block {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: 2px;
  padding: 0 4px;
  border-left: 1px solid rgba(255, 255, 255, 0.15);
}
.viewer-scene-tint-label {
  font-size: 0.68rem;
  color: #c6d4e8;
  text-transform: uppercase;
}
.viewer-scene-shading {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.7rem;
  color: #d0d6e6;
}
.viewer-scene-part-colors {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.7rem;
  color: #d0d6e6;
  margin-left: 0.2rem;
}
.viewer-scene-part-colors input {
  width: 0.9rem;
  height: 0.9rem;
  accent-color: #6a8bc7;
}
.viewer-scene-select {
  height: 24px;
  font-size: 0.68rem;
  color: #e8edf6;
  background: rgba(40, 50, 75, 0.95);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 5px;
  padding: 0 0.35rem;
}
.viewer-scene-tint-range {
  width: 90px;
}
.viewer-scene-frame-opacity-input {
  width: 2.2rem;
  padding: 2px 4px;
  font-size: 0.7rem;
  color: #e0e0e0;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 4px;
  text-align: center;
}
.viewer-scene-frame-opacity-input::-webkit-inner-spin-button {
  opacity: 1;
}
.viewer-scene-menu {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 4px;
  min-width: 100px;
  background: #2a2e38;
  border: 1px solid #555;
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
  padding: 4px;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.viewer-scene-item,
.viewer-scene-item-label,
.viewer-scene-item-text {
  padding: 6px 10px;
  font-size: 0.8rem;
  color: #e0e0e0;
  background: transparent;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  text-align: left;
  width: 100%;
}
.viewer-scene-item:hover {
  background: rgba(80, 110, 150, 0.5);
}
.loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.loading-text {
  font-size: 1.1rem;
  color: #333;
}
.viewer-settings-open-btn {
  margin-left: 6px;
}
.viewer-settings-backdrop {
  position: fixed;
  inset: 0;
  z-index: 12000;
  background: rgba(10, 14, 22, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}
.viewer-settings-modal {
  width: min(520px, 96vw);
  max-height: min(86vh, 720px);
  overflow: auto;
  background: #1e2430;
  border: 1px solid #4a5568;
  border-radius: 10px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
  color: #e8edf5;
}
.viewer-settings-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #3a4455;
}
.viewer-settings-head h2 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
}
.viewer-settings-close {
  border: none;
  background: transparent;
  color: #cbd5e1;
  font-size: 1.4rem;
  line-height: 1;
  cursor: pointer;
}
.viewer-settings-body {
  padding: 12px 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.viewer-settings-section h3 {
  margin: 0 0 8px;
  font-size: 0.85rem;
  color: #94a3b8;
  font-weight: 600;
}
.viewer-settings-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
  align-items: center;
  margin-bottom: 8px;
  font-size: 0.82rem;
}
.viewer-settings-row-check {
  grid-template-columns: 1fr auto;
}
.viewer-settings-color {
  width: 48px;
  height: 28px;
  padding: 0;
  border: 1px solid #64748b;
  border-radius: 4px;
  background: transparent;
}
.viewer-component-tree-empty {
  padding: 12px;
  font-size: 0.82rem;
  color: #94a3b8;
  line-height: 1.45;
}
.viewer-component-item-count {
  margin-left: 6px;
  font-size: 0.72rem;
  color: #94a3b8;
}
.viewer-models-card-focused {
  outline: 2px solid #5b8def;
  outline-offset: -2px;
}
</style>
