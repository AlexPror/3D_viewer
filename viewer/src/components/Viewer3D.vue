<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import * as THREE from 'three'
import { TrackballControls } from 'three/addons/controls/TrackballControls.js'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js'
import { STLExporter } from 'three/addons/exporters/STLExporter.js'
import { loadStepOrIgesToGlbUrl, getOpenCascade } from '../lib/stepLoader'

const containerRef = ref<HTMLDivElement | null>(null)
const isLoading = ref(false)
const emit = defineEmits<{
  'section-active': []
  'section-inactive': []
  'section-offset-changed': [value: number]
}>()

let scene: THREE.Scene
let sectionPlane: THREE.Plane | null = null
let currentSectionAxis: 'x' | 'y' | 'z' | null = null
let currentSectionOffset = 0
let camera: THREE.PerspectiveCamera
let renderer: THREE.WebGLRenderer
let controls: InstanceType<typeof TrackballControls>
let meshGroup: THREE.Group
let measureGroup: THREE.Group
let raycaster: THREE.Raycaster
let mouse: THREE.Vector2
let measurementPoints: THREE.Vector3[] = []
let measurementLine: THREE.Line | null = null
let measurementLabelEl: HTMLDivElement | null = null
const measureModeRef = ref(false)
const sectionModeRef = ref(false)
let sectionPlaneMesh: THREE.Mesh | null = null
let sectionPlaneBasePoint: THREE.Vector3 | null = null
let sectionPlaneNormal: THREE.Vector3 | null = null
let sectionPlaneClipNormal: THREE.Vector3 | null = null
let sectionPlaneOffset = 0
const SECTION_OFFSET_MIN = -2000
const SECTION_OFFSET_MAX = 2000
let animationId: number
export type MeasureSnapMode = 'intersection' | 'vertex' | 'face' | 'edge'
let measureSnapMode: MeasureSnapMode = 'intersection'
let fileInput: HTMLInputElement | null = null
let loadedFileName: string | null = null
const savedCameraPosition = new THREE.Vector3(500, 400, 500)
const savedCameraTarget = new THREE.Vector3(0, 0, 0)

const DEFAULT_COLOR = 0x888888
const DEFAULT_SPECULAR = 0x222222

function initScene() {
  if (!containerRef.value) return

  scene = new THREE.Scene()
  scene.background = new THREE.Color(0xffffff)

  camera = new THREE.PerspectiveCamera(
    50,
    containerRef.value.clientWidth / containerRef.value.clientHeight,
    0.1,
    10000
  )
  camera.position.set(500, 400, 500)

  renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true })
  renderer.setSize(containerRef.value.clientWidth, containerRef.value.clientHeight)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1
  renderer.localClippingEnabled = true
  containerRef.value.appendChild(renderer.domElement)

  controls = new TrackballControls(camera, renderer.domElement)
  controls.rotateSpeed = 6.4
  controls.zoomSpeed = 0.9
  controls.panSpeed = 2
  controls.staticMoving = false
  controls.dynamicDampingFactor = 0.22
  controls.minDistance = 10
  controls.maxDistance = 5000
  controls.target.set(0, 0, 0)
  controls.mouseButtons = {
    LEFT: -1,
    MIDDLE: THREE.MOUSE.PAN,
    RIGHT: THREE.MOUSE.ROTATE,
  }
  controls.handleResize()
  savedCameraPosition.copy(camera.position)
  savedCameraTarget.copy(controls.target)

  const ambient = new THREE.AmbientLight(0xffffff, 0.6)
  scene.add(ambient)
  const dir = new THREE.DirectionalLight(0xffffff, 0.8)
  dir.position.set(400, 600, 400)
  scene.add(dir)
  const dir2 = new THREE.DirectionalLight(0xffffff, 0.3)
  dir2.position.set(-300, 200, -300)
  scene.add(dir2)

  meshGroup = new THREE.Group()
  scene.add(meshGroup)

  measureGroup = new THREE.Group()
  scene.add(measureGroup)
  raycaster = new THREE.Raycaster()
  mouse = new THREE.Vector2()
  measurementLabelEl = document.createElement('div')
  measurementLabelEl.className = 'measurement-label'
  measurementLabelEl.style.cssText =
    'position:absolute;pointer-events:none;color:#fff;background:rgba(0,0,0,0.75);padding:2px 8px;border-radius:4px;font-size:12px;white-space:nowrap;display:none;'
  containerRef.value.appendChild(measurementLabelEl)
  renderer.domElement.addEventListener('click', onCanvasClick)

  function animate() {
    animationId = requestAnimationFrame(animate)
    controls.update()
    if (measurementPoints.length === 2 && measurementLabelEl && containerRef.value) {
      const mid = measurementPoints[0].clone().add(measurementPoints[1]).multiplyScalar(0.5)
      mid.project(camera)
      const rect = containerRef.value.getBoundingClientRect()
      measurementLabelEl.style.left = (mid.x * 0.5 + 0.5) * rect.width + 'px'
      measurementLabelEl.style.top = (-mid.y * 0.5 + 0.5) * rect.height + 'px'
      const p0 = measurementPoints[0]
      const p1 = measurementPoints[1]
      const d = p0.distanceTo(p1)
      const dx = p1.x - p0.x
      const dy = p1.y - p0.y
      const dz = p1.z - p0.z
      measurementLabelEl.textContent =
        `L: ${d.toFixed(2)} mm  ΔX: ${dx.toFixed(2)}  ΔY: ${dy.toFixed(2)}  ΔZ: ${dz.toFixed(2)} mm`
      measurementLabelEl.style.display = 'block'
    } else if (measurementLabelEl) {
      measurementLabelEl.style.display = 'none'
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
  renderer.setSize(w, h)
  controls?.handleResize()
}

function centerModel(box: THREE.Box3) {
  const center = box.getCenter(new THREE.Vector3())
  const size = box.getSize(new THREE.Vector3())
  const maxDim = Math.max(size.x, size.y, size.z)
  const distance = maxDim * 1.5
  camera.position.set(center.x + distance * 0.6, center.y + distance * 0.5, center.z + distance * 0.6)
  controls.target.copy(center)
  controls.update()
  savedCameraPosition.copy(camera.position)
  savedCameraTarget.copy(controls.target)
}

function resetView() {
  if (!camera || !controls) return
  camera.position.copy(savedCameraPosition)
  controls.target.copy(savedCameraTarget)
  controls.update()
}

function applySectionToMeshGroup(plane: THREE.Plane | null) {
  const planes = plane ? [plane] : []
  meshGroup.traverse((obj: THREE.Object3D) => {
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
}

function onCanvasClick(ev: MouseEvent) {
  if (!renderer || !camera || !meshGroup.children.length) return
  const rect = renderer.domElement.getBoundingClientRect()
  mouse.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1
  mouse.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1
  raycaster.setFromCamera(mouse, camera)
  const hits = raycaster.intersectObject(meshGroup, true)
  if (sectionModeRef.value) {
    if (hits.length === 0) return
    const hit = hits[0]
    const worldNormal = hit.face!.normal.clone().transformDirection(hit.object.matrixWorld)
    setSectionFromHit(hit.point.clone(), worldNormal)
    return
  }
  if (!measureModeRef.value) return
  if (hits.length === 0) return
  const point = getPointFromHit(hits[0])
  if (measurementPoints.length >= 2) {
    clearMeasurements()
    measurementPoints = [point]
  } else {
    measurementPoints.push(point)
  }
  if (measurementPoints.length === 2) {
    if (measurementLine) {
      measureGroup.remove(measurementLine)
      measurementLine.geometry.dispose()
      ;(measurementLine.material as THREE.Material).dispose()
    }
    const geom = new THREE.BufferGeometry().setFromPoints(measurementPoints)
    const mat = new THREE.LineBasicMaterial({ color: 0xff0000, linewidth: 2 })
    measurementLine = new THREE.Line(geom, mat)
    measureGroup.add(measurementLine)
  }
}

function clearMeasurements() {
  if (measurementLine) {
    measureGroup.remove(measurementLine)
    measurementLine.geometry.dispose()
    ;(measurementLine.material as THREE.Material).dispose()
    measurementLine = null
  }
  measurementPoints = []
  if (measurementLabelEl) measurementLabelEl.style.display = 'none'
}

function setMeasureMode(enabled: boolean) {
  measureModeRef.value = enabled
  if (!enabled) clearMeasurements()
}

function setMeasureSnapMode(mode: MeasureSnapMode) {
  measureSnapMode = mode
}

function getMeasureSnapMode(): MeasureSnapMode {
  return measureSnapMode
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
        if (obj instanceof THREE.Mesh) {
          obj.geometry?.dispose()
          if (obj.material) {
            const mat = obj.material
            Array.isArray(mat) ? mat.forEach((m: THREE.Material) => m.dispose()) : mat.dispose()
          }
        }
      })
    }
  }
}

function loadGlbUrl(url: string, loadStartedAt?: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const loader = new GLTFLoader()
    loader.load(
      url,
      (gltf) => {
        const t0 = loadStartedAt ?? performance.now()
        clearMeshGroup()
        meshGroup.add(gltf.scene)
        if (currentSectionAxis) setSectionAxis(currentSectionAxis)
        else if (sectionPlane) applySectionToMeshGroup(sectionPlane)
        const box = new THREE.Box3().setFromObject(meshGroup)
        const size = box.getSize(new THREE.Vector3())
        const sceneMs = performance.now() - t0
        console.log(
          `${LOG_PREFIX} GLB: габариты ${size.x.toFixed(1)} x ${size.y.toFixed(1)} x ${size.z.toFixed(1)}, загрузка в сцену: ${(sceneMs / 1000).toFixed(2)} с`
        )
        centerModel(box)
        URL.revokeObjectURL(url)
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

function loadSTL(arrayBuffer: ArrayBuffer, _filename: string) {
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
  clearMeshGroup()
  meshGroup.add(mesh)
  if (currentSectionAxis) setSectionAxis(currentSectionAxis)
  else if (sectionPlane) applySectionToMeshGroup(sectionPlane)
  const box = new THREE.Box3().setFromObject(meshGroup)
  const size = box.getSize(new THREE.Vector3())
  console.log(`${LOG_PREFIX} STL: габариты модели ${size.x.toFixed(1)} x ${size.y.toFixed(1)} x ${size.z.toFixed(1)}, центрирование камеры`)
  centerModel(box)
}

const LOG_PREFIX = '[Viewer3D]'

function handleFile(file: File) {
  const ext = (file.name.split('.').pop() || '').toLowerCase()
  console.groupCollapsed(`${LOG_PREFIX} Загрузка файла: ${file.name}`)
  console.log('имя:', file.name)
  console.log('расширение:', ext)
  console.log('размер (байт):', file.size)
  console.log('тип MIME:', file.type || '(не задан)')
  const reader = new FileReader()
  reader.onload = () => {
    loadedFileName = file.name
    const buf = reader.result as ArrayBuffer
    console.log('ArrayBuffer (байт):', buf?.byteLength ?? 0)
    if (ext === 'stl') {
      console.log('формат: STL — загрузка через STLLoader')
      console.groupEnd()
      loadSTL(buf, file.name)
      return
    }
    if (['step', 'stp', 'igs', 'iges'].includes(ext)) {
      console.log(`формат: ${ext.toUpperCase()} — загрузка через opencascade.js`)
      console.groupEnd()
      isLoading.value = true
      const t0 = performance.now()
      loadStepOrIgesToGlbUrl(buf, ext)
        .then((glbUrl) => loadGlbUrl(glbUrl, performance.now()))
        .then(() => {
          const totalMs = performance.now() - t0
          console.log(`${LOG_PREFIX} Модель загружена. Всего: ${(totalMs / 1000).toFixed(2)} с`)
        })
        .catch((err) => {
          console.error(`${LOG_PREFIX} Ошибка загрузки STEP/IGES:`, err)
          if (err instanceof Error) console.error(`${LOG_PREFIX} message:`, err.message, 'stack:', err.stack)
        })
        .finally(() => {
          isLoading.value = false
        })
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
            const text = await res.text()
            let msg = res.statusText
            try {
              const body = JSON.parse(text)
              msg = body.detail ? `${body.error || ''}: ${body.detail}` : (body.error || msg)
            } catch (_) {
              if (text) msg = text.slice(0, 200)
            }
            throw new Error(msg)
          }
          return res.blob()
        })
        .then((blob) => {
          console.log(`${LOG_PREFIX} JT blob size:`, blob.size, blob.type)
          const url = URL.createObjectURL(blob)
          return loadGlbUrl(url, performance.now())
        })
        .then(() => {
          console.log(`${LOG_PREFIX} JT loadGlbUrl done`)
          loadedFileName = file.name
        })
        .catch((err) => {
          console.error(`${LOG_PREFIX} Ошибка конвертации JT:`, err)
          alert('Ошибка конвертации JT: ' + (err instanceof Error ? err.message : String(err)))
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
  }
  reader.onerror = () => {
    console.error(`${LOG_PREFIX} Ошибка чтения файла:`, file.name, reader.error)
    console.groupEnd()
  }
  reader.readAsArrayBuffer(file)
}

function openFileDialog() {
  if (!fileInput) {
    fileInput = document.createElement('input')
    fileInput.type = 'file'
    fileInput.accept = '.stl,.step,.stp,.igs,.iges,.dxf'
    fileInput.multiple = false
    fileInput.onchange = () => {
      const file = fileInput?.files?.[0]
      if (file) handleFile(file)
      if (fileInput) fileInput.value = ''
    }
  }
  fileInput.click()
}

function takeScreenshot(): Promise<string> {
  return new Promise((resolve) => {
    if (!renderer || !scene || !camera) {
      resolve('')
      return
    }
    renderer.render(scene, camera)
    const dataUrl = renderer.domElement.toDataURL('image/png')
    resolve(dataUrl)
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
    alert('Загрузите 3D модель')
    return Promise.resolve()
  }
  const exporter = new GLTFExporter()
  const name = (loadedFileName ?? 'model').replace(/\.[^.]+$/, '') || 'model'
  return exporter
    .parseAsync(meshGroup, { binary: true })
    .then((arrayBuffer) => {
      downloadBlob(new Blob([arrayBuffer as ArrayBuffer], { type: 'model/gltf-binary' }), `${name}.glb`)
    })
    .catch((err) => {
      console.error(`${LOG_PREFIX} exportGlb:`, err)
      alert('Ошибка экспорта GLB')
    })
}

function exportStl(): void {
  if (!meshGroup || meshGroup.children.length === 0) {
    alert('Загрузите 3D модель')
    return
  }
  const exporter = new STLExporter()
  const data = exporter.parse(meshGroup, { binary: true }) as ArrayBuffer
  const name = (loadedFileName ?? 'model').replace(/\.[^.]+$/, '') || 'model'
  downloadBlob(new Blob([data], { type: 'application/octet-stream' }), `${name}.stl`)
}

onMounted(() => {
  initScene()
  getOpenCascade().then(() => {
    console.log(`${LOG_PREFIX} WASM предзагружен (первый STEP/IGES откроется быстрее)`)
  })
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  if (renderer?.domElement) renderer.domElement.removeEventListener('click', onCanvasClick)
  if (sectionPlaneMesh) {
    scene.remove(sectionPlaneMesh)
    sectionPlaneMesh.geometry.dispose()
    ;(sectionPlaneMesh.material as THREE.Material).dispose()
    sectionPlaneMesh = null
  }
  if (measurementLabelEl && containerRef.value?.contains(measurementLabelEl)) {
    containerRef.value.removeChild(measurementLabelEl)
  }
  measurementLabelEl = null
  if (animationId) cancelAnimationFrame(animationId)
  controls?.dispose()
  renderer?.dispose()
  if (containerRef.value && renderer?.domElement) {
    containerRef.value.removeChild(renderer.domElement)
  }
})

function loadModelFile(file: File) {
  handleFile(file)
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

defineExpose({
  openFileDialog,
  loadModelFile,
  takeScreenshot,
  getLoadedFileName: () => loadedFileName,
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
  clearMeasurements,
  exportGlb,
  exportStl,
})
</script>

<template>
  <div class="viewer-wrap">
    <div ref="containerRef" class="viewer-container" />
    <div v-if="isLoading" class="loading-overlay">
      <span class="loading-text">Загрузка модели…</span>
    </div>
  </div>
</template>

<style scoped>
.viewer-wrap {
  flex: 1;
  min-height: 0;
  position: relative;
}
.viewer-container {
  position: absolute;
  inset: 0;
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
</style>
