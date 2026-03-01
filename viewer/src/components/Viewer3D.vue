<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import * as THREE from 'three'
import { TrackballControls } from 'three/addons/controls/TrackballControls.js'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js'
import { STLExporter } from 'three/addons/exporters/STLExporter.js'
import { loadStepOrIgesToGlbUrl, getOpenCascade } from '../lib/stepLoader'
import { logger } from '../lib/logger'

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
let highlightGroup: THREE.Group
let axesHelper: THREE.Group | null = null
let raycaster: THREE.Raycaster
let mouse: THREE.Vector2
let measurementPoints: THREE.Vector3[] = []
let measurementPointNormals: (THREE.Vector3 | null)[] = []
let measurementLine: THREE.Line | null = null
let measurementTriangleLines: THREE.Line[] = []
let measurementPerpLine: THREE.Line | null = null
let measurementCircleMesh: THREE.LineLoop | null = null
let measurementCircleMesh2: THREE.LineLoop | null = null
let measurementArcPathLine: THREE.Line | null = null
let measurementLabelEl: HTMLDivElement | null = null
let measurementPerpLabelEl: HTMLDivElement | null = null
let measurementExtraLabelEl: HTMLDivElement | null = null
let measurementLabelEl0: HTMLDivElement | null = null
let measurementLabelEl1: HTMLDivElement | null = null
let measurementLabelEl2: HTMLDivElement | null = null
let hoverTooltipEl: HTMLDivElement | null = null
let lastHoverNormal: THREE.Vector3 | null = null
let lastHoverPoint: THREE.Vector3 | null = null
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
export type MeasureType = 'distance' | 'radius' | 'diameter' | 'arc' | 'hole-center-distance'
let measureSnapMode: MeasureSnapMode = 'intersection'
let measureType: MeasureType = 'distance'
let fileInput: HTMLInputElement | null = null
let loadedFileName: string | null = null
const savedCameraPosition = new THREE.Vector3(500, 400, 500)
const savedCameraTarget = new THREE.Vector3(0, 0, 0)

const DEFAULT_COLOR = 0x888888
const DEFAULT_SPECULAR = 0x222222
const SNAP_SCREEN_THRESHOLD = 0.08
const snapProj = new THREE.Vector3()

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
  controls.noZoom = true
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
  highlightGroup = new THREE.Group()
  scene.add(highlightGroup)

  const axesSize = 100
  axesHelper = new THREE.Group()
  const axes = new THREE.AxesHelper(axesSize)
  axesHelper.add(axes)
  scene.add(axesHelper)

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
  renderer.domElement.addEventListener('click', onCanvasClick)
  renderer.domElement.addEventListener('mousedown', onCanvasMouseDown, true)
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
    const tFrame = performance.now()
    controls.update()
    let hits: THREE.Intersection[] = []
    let rayMs = 0
    let holeMs = 0
    let zoneMs = 0
    if (measureModeRef.value && meshGroup.children.length && containerRef.value) {
      holeMs = 0
      zoneMs = 0
      const rect = renderer.domElement.getBoundingClientRect()
      raycaster.setFromCamera(mouse, camera)
      const tRay = performance.now()
      hits = raycaster.intersectObject(meshGroup, true)
      rayMs = performance.now() - tRay
      while (highlightGroup.children.length) {
        const c = highlightGroup.children[0]
        highlightGroup.remove(c)
        if ('geometry' in c && c.geometry) c.geometry.dispose()
        if ('material' in c && c.material) (c.material as THREE.Material).dispose()
      }
      if (hits.length > 0) {
        const hit = hits[0]
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
          const tHole = performance.now()
          let holeInfo = getHoverHoleInfo(mesh, hit.point)
          holeMs = performance.now() - tHole
          let radiusInfo: { center: THREE.Vector3; radius: number } | null =
            holeInfo ? null : getHoverRadiusInfo(mesh, faceIndex, worldNormal)
          if (!holeInfo && radiusInfo && isCylinderAHole(mesh, radiusInfo.center, radiusInfo.radius, worldNormal, raycaster)) {
            holeInfo = { center: radiusInfo.center.clone(), radius: radiusInfo.radius, normal: worldNormal.clone() }
            radiusInfo = null
          }
          // 1) Всегда подсвечиваем поверхность под курсором (валидация выбора)
          const tZone = performance.now()
          const surfaceZoneGeom = getCylindricalZoneGeometry(mesh, faceIndex, worldNormal)
          const surfaceFaceGeom =
            surfaceZoneGeom ??
            getCoplanarFaceGeometry(mesh, faceIndex) ??
            (() => {
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
            })()
          zoneMs = performance.now() - tZone
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
          const showHoleCylinderHighlight =
            measureType === 'radius' || measureType === 'diameter' || measureType === 'hole-center-distance'
          if (holeInfo) {
            const n = holeInfo.normal
            const u = new THREE.Vector3().crossVectors(n, new THREE.Vector3(1, 0, 0)).normalize()
            if (u.lengthSq() < 0.01) u.crossVectors(n, new THREE.Vector3(0, 1, 0)).normalize()
            const v = new THREE.Vector3().crossVectors(n, u).normalize()
            const r = holeInfo.radius
            candidates = [
              holeInfo.center.clone(),
              holeInfo.center.clone().add(u.clone().multiplyScalar(r)),
              holeInfo.center.clone().sub(u.clone().multiplyScalar(r)),
              holeInfo.center.clone().add(v.clone().multiplyScalar(r)),
              holeInfo.center.clone().sub(v.clone().multiplyScalar(r)),
              ...candidates,
            ]
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
            candidates = [radiusInfo.center.clone(), ...candidates]
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

          const closest = getClosestSnapPoint(candidates, camera, mouse)
          if (closest !== null) {
            const sphereGeom = new THREE.SphereGeometry(2, 12, 10)
            const sphereMat = new THREE.MeshBasicMaterial({ color: 0xffff00 })
            const sphereMesh = new THREE.Mesh(sphereGeom, sphereMat)
            sphereMesh.position.copy(closest)
            highlightGroup.add(sphereMesh)
          }

          if (holeInfo && hoverTooltipEl) {
            const screen = hit.point.clone().project(camera)
            hoverTooltipEl.style.left = (screen.x * 0.5 + 0.5) * rect.width + 'px'
            hoverTooltipEl.style.top = (-screen.y * 0.5 + 0.5) * rect.height + 'px'
            hoverTooltipEl.textContent = `Отверстие · D = ${(2 * holeInfo.radius).toFixed(2)}`
            hoverTooltipEl.style.display = 'block'
          } else if (radiusInfo && hoverTooltipEl) {
            const screen = hit.point.clone().project(camera)
            hoverTooltipEl.style.left = (screen.x * 0.5 + 0.5) * rect.width + 'px'
            hoverTooltipEl.style.top = (-screen.y * 0.5 + 0.5) * rect.height + 'px'
            hoverTooltipEl.textContent = `R = ${radiusInfo.radius.toFixed(2)}`
            hoverTooltipEl.style.display = 'block'
          } else if (hoverTooltipEl) {
            hoverTooltipEl.style.display = 'none'
          }
        } else if (hoverTooltipEl) {
          hoverTooltipEl.style.display = 'none'
        }
      } else {
        if (hoverTooltipEl) hoverTooltipEl.style.display = 'none'
        lastHoverNormal = null
        lastHoverPoint = null
      }
      }
    if (measurementPoints.length === 3 && containerRef.value && measurementLabelEl0 && measurementLabelEl1 && measurementLabelEl2) {
      const rect = containerRef.value.getBoundingClientRect()
      const p0 = measurementPoints[0]
      const p1 = measurementPoints[1]
      const p2 = measurementPoints[2]
      const midpoints = [
        p0.clone().add(p1).multiplyScalar(0.5),
        p1.clone().add(p2).multiplyScalar(0.5),
        p2.clone().add(p0).multiplyScalar(0.5),
      ]
      const lengths = [
        p0.distanceTo(p1),
        p1.distanceTo(p2),
        p2.distanceTo(p0),
      ]
      const labels = [measurementLabelEl0, measurementLabelEl1, measurementLabelEl2]
      for (let i = 0; i < 3; i++) {
        midpoints[i].project(camera)
        labels[i].style.left = (midpoints[i].x * 0.5 + 0.5) * rect.width + 'px'
        labels[i].style.top = (-midpoints[i].y * 0.5 + 0.5) * rect.height + 'px'
        labels[i].textContent = `${lengths[i].toFixed(2)}`
        labels[i].style.display = 'block'
      }
      if (measurementLabelEl) measurementLabelEl.style.display = 'none'
      if (measurementPerpLabelEl) measurementPerpLabelEl.style.display = 'none'
    } else if (measurementPoints.length === 2 && measureType === 'hole-center-distance' && containerRef.value && measurementLabelEl) {
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
    } else if (measureType === 'diameter' && firstClickHole && secondHoleResult && measurementPoints.length === 2 && containerRef.value && measurementExtraLabelEl && diameterSecondLabelEl && measurementLabelEl && measurementLabelEl0 && measurementLabelEl1 && measurementLabelEl2) {
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
    } else if (measurementPoints.length === 2 && (measureType !== 'hole-center-distance' || (measureType === 'diameter' && firstClickHole && !secondHoleResult)) && containerRef.value && measurementLabelEl0 && measurementLabelEl1 && measurementLabelEl2) {
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
      const texts = [
        `${L.toFixed(2)}`,
        `${L_parallel.toFixed(2)}`,
        `${L_perp.toFixed(2)}`,
      ]
      const labels = [measurementLabelEl0, measurementLabelEl1, measurementLabelEl2]
      for (let i = 0; i < 3; i++) {
        midpoints[i].project(camera)
        labels[i].style.left = (midpoints[i].x * 0.5 + 0.5) * rect.width + 'px'
        labels[i].style.top = (-midpoints[i].y * 0.5 + 0.5) * rect.height + 'px'
        labels[i].textContent = texts[i]
        labels[i].style.display = 'block'
      }
      if (measurementLabelEl) measurementLabelEl.style.display = 'none'
      if (measureType === 'diameter' && firstClickHole && measurementExtraLabelEl) {
        const dc = firstClickHole.center.clone()
        dc.project(camera)
        measurementExtraLabelEl.style.left = (dc.x * 0.5 + 0.5) * rect.width + 'px'
        measurementExtraLabelEl.style.top = (-dc.y * 0.5 + 0.5) * rect.height + 'px'
        measurementExtraLabelEl.textContent = (2 * firstClickHole.radius).toFixed(2)
        measurementExtraLabelEl.style.display = 'block'
      } else if (measurementExtraLabelEl) {
        measurementExtraLabelEl.style.display = 'none'
      }
      if (diameterSecondLabelEl) diameterSecondLabelEl.style.display = 'none'
      const nA = measurementPointNormals[0] ?? null
      const nB = measurementPointNormals[1] ?? null
      if (measurementPerpLabelEl && (nA || nB)) {
        const baseNormal = (nB || nA)!.clone().normalize()
        const basePoint = nB ? B : A
        const otherPoint = nB ? A : B
        const v = otherPoint.clone().sub(basePoint)
        const distSigned = v.dot(baseNormal)
        const proj = otherPoint.clone().sub(baseNormal.clone().multiplyScalar(distSigned))
        const midPerp = otherPoint.clone().add(proj).multiplyScalar(0.5)
        midPerp.project(camera)
        measurementPerpLabelEl.style.left = (midPerp.x * 0.5 + 0.5) * rect.width + 'px'
        measurementPerpLabelEl.style.top = (-midPerp.y * 0.5 + 0.5) * rect.height + 'px'
        measurementPerpLabelEl.textContent = `${Math.abs(distSigned).toFixed(2)}`
        measurementPerpLabelEl.style.display = 'block'
      } else if (measurementPerpLabelEl) {
        measurementPerpLabelEl.style.display = 'none'
      }
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
      const tRender = performance.now()
      renderer.render(scene, camera)
      const renderMs = performance.now() - tRender
      const totalMs = performance.now() - tFrame
      if (hits.length > 0) {
        console.log(
          '[animate] ray:', rayMs.toFixed(1), 'ms | hole:', holeMs.toFixed(1), 'ms | zone:', zoneMs.toFixed(1), 'ms | render:', renderMs.toFixed(1), 'ms | total:', totalMs.toFixed(1), 'ms'
        )
      } else if (totalMs > 50) {
        console.log('[animate] (no hit) render:', renderMs.toFixed(1), 'ms | total:', totalMs.toFixed(1), 'ms')
      }
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
  if (axesHelper && maxDim > 0) {
    const axesLen = Math.max(maxDim * 0.15, 10)
    axesHelper.scale.setScalar(axesLen / 100)
  }
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
  logger.info('Viewer3D', `Режим сечения: ${enabled ? 'вкл' : 'выкл'}`)
}

function updateMouseFromClient(clientX: number, clientY: number) {
  if (!renderer?.domElement) return
  const rect = renderer.domElement.getBoundingClientRect()
  mouse.x = ((clientX - rect.left) / rect.width) * 2 - 1
  mouse.y = -((clientY - rect.top) / rect.height) * 2 + 1
}

function onCanvasMouseMove(ev: MouseEvent) {
  updateMouseFromClient(ev.clientX, ev.clientY)
}

function onContainerMouseMove(ev: MouseEvent) {
  updateMouseFromClient(ev.clientX, ev.clientY)
}

const zoomToCursorPlane = new THREE.Plane()
const zoomToCursorPoint = new THREE.Vector3()
const zoomToCursorDir = new THREE.Vector3()
const ZOOM_GESTURE_MS = 450
let zoomAnchorPoint: THREE.Vector3 | null = null
let lastWheelTime = 0

const mouseDownPlane = new THREE.Plane()
const mouseDownPoint = new THREE.Vector3()
const mouseDownDir = new THREE.Vector3()

let panAnchorPoint: THREE.Vector3 | null = null
let isPanningWithAnchor = false
const panRaycaster = new THREE.Raycaster()
const panRayDir = new THREE.Vector3()

function getPointUnderCursor(clientX: number, clientY: number): THREE.Vector3 | null {
  if (!camera || !controls || !renderer?.domElement) return null
  const rect = renderer.domElement.getBoundingClientRect()
  const mx = ((clientX - rect.left) / rect.width) * 2 - 1
  const my = -((clientY - rect.top) / rect.height) * 2 + 1
  const r = new THREE.Raycaster()
  r.setFromCamera(new THREE.Vector2(mx, my), camera)
  mouseDownPlane.setFromNormalAndCoplanarPoint(
    mouseDownDir.copy(camera.position).sub(controls.target).normalize(),
    controls.target
  )
  const out = new THREE.Vector3()
  return r.ray.intersectPlane(mouseDownPlane, out) ? out : null
}

function onCanvasMouseDown(ev: MouseEvent) {
  if (!camera || !controls) return
  if (ev.button === 1) {
    const pt = getPointUnderCursor(ev.clientX, ev.clientY)
    if (pt) {
      panAnchorPoint = pt.clone()
      isPanningWithAnchor = true
      controls.enabled = false
      ev.preventDefault()
      ev.stopPropagation()
    }
    return
  }
  // Правая кнопка — только вращение через TrackballControls, не сдвигаем target
}

function onCanvasMouseMovePan(ev: MouseEvent) {
  if (!isPanningWithAnchor || !panAnchorPoint || !camera || !controls) return
  ev.preventDefault()
  ev.stopPropagation()
  const rect = renderer.domElement.getBoundingClientRect()
  const mx = ((ev.clientX - rect.left) / rect.width) * 2 - 1
  const my = -((ev.clientY - rect.top) / rect.height) * 2 + 1
  panRaycaster.setFromCamera(new THREE.Vector2(mx, my), camera)
  panRayDir.copy(panRaycaster.ray.direction)
  const dist = camera.position.distanceTo(panAnchorPoint)
  camera.position.copy(panAnchorPoint).sub(panRayDir.multiplyScalar(dist))
  controls.target.copy(panAnchorPoint)
}

function onCanvasMouseUp(ev: MouseEvent) {
  if (ev.button === 1 && isPanningWithAnchor) {
    isPanningWithAnchor = false
    panAnchorPoint = null
    if (controls) controls.enabled = true
    ev.preventDefault()
    ev.stopPropagation()
  }
}

function onCanvasWheel(ev: WheelEvent) {
  if (!camera || !controls || !containerRef.value) return
  ev.preventDefault()
  const now = performance.now()
  const rect = renderer.domElement.getBoundingClientRect()
  const mx = ((ev.clientX - rect.left) / rect.width) * 2 - 1
  const my = -((ev.clientY - rect.top) / rect.height) * 2 + 1
  if (zoomAnchorPoint === null || now - lastWheelTime > ZOOM_GESTURE_MS) {
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
  const zoomFactor = 1 + (ev.deltaY > 0 ? -0.032 : 0.032) * Math.max(1, dist * 0.001)
  let newDist = dist * zoomFactor
  newDist = Math.max(controls.minDistance, Math.min(controls.maxDistance, newDist))
  const dirFromPoint = camera.position.clone().sub(zoomAnchorPoint).normalize()
  camera.position.copy(zoomAnchorPoint).add(dirFromPoint.multiplyScalar(newDist))
  controls.target.copy(zoomAnchorPoint)
}

function onCanvasClick(ev: MouseEvent) {
  if (!renderer || !camera || !meshGroup.children.length) {
    if (measureModeRef.value) logger.info('Viewer3D', 'Клик: модель не загружена или нет сцены, измерение игнорируется')
    return
  }
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
  logger.info('Viewer3D', `Клик в режиме измерений: measureType=${measureType}, hitsCount=${hits.length}`)
  if (measureType === 'radius') {
    if (hits.length === 0) return
    const hit = hits[0]
    const mesh = hit.object as THREE.Mesh
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
      updateMeasurementGraphics()
    }
    return
  }
  if (measureType === 'diameter') {
    if (hits.length === 0) return
    if (firstClickHole && measurementPoints.length === 2) {
      firstClickHole = null
      secondHoleResult = null
      measurementPoints = []
      measurementPointNormals = []
      radiusOrDiameterResult = null
      updateMeasurementGraphics()
    }
    const hit = hits[0]
    const mesh = hit.object as THREE.Mesh
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
      radiusOrDiameterResult = { center: hole.center, radius: hole.radius, normal: hole.normal, isDiameter: true }
      updateMeasurementGraphics()
      return
    }
    if (hole) {
      secondHoleResult = { center: hole.center.clone(), radius: hole.radius, normal: hole.normal.clone() }
      measurementPoints = [firstClickHole.center.clone(), secondHoleResult.center.clone()]
      measurementPointNormals = [null, null]
    } else {
      const candidates = getSnapCandidates(hit)
      const closest = getClosestSnapPoint(candidates, camera, mouse)
      const point = (closest ?? getPointFromHit(hit)).clone()
      const worldNormal = hit.face!.normal.clone().transformDirection(mesh.matrixWorld).normalize()
      measurementPoints = [firstClickHole.center.clone(), point]
      measurementPointNormals = [firstClickHole.normal.clone(), worldNormal]
    }
    updateMeasurementGraphics()
    return
  }
  if (measureType === 'arc') {
    if (hits.length === 0) return
    const hit = hits[0]
    const mesh = hit.object as THREE.Mesh
    const candidates = getSnapCandidates(hit)
    const closest = getClosestSnapPoint(candidates, camera, mouse)
    const point = (closest ?? getPointFromHit(hit)).clone()
    if (arcFirstPoint === null) {
      arcFirstPoint = point
      arcMesh = mesh
      return
    }
    const result = shortestPathOnMesh(arcMesh!, arcFirstPoint, point)
    arcFirstPoint = null
    arcMesh = null
    if (result) {
      arcResult = result
      updateMeasurementGraphics()
    }
    return
  }
  if (measureType === 'hole-center-distance') {
    if (hits.length === 0) return
    const hit = hits[0]
    const mesh = hit.object as THREE.Mesh
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
      if (!fit) return
      center = fit.center.clone()
    } else {
      const radiusInfo = getHoverRadiusInfo(mesh, faceIndex, worldNormalHit)
      if (!radiusInfo || !isCylinderAHole(mesh, radiusInfo.center, radiusInfo.radius, worldNormalHit, raycaster)) return
      center = radiusInfo.center.clone()
    }
    if (holeCenterFirst === null) {
      holeCenterFirst = center
      return
    }
    measurementPoints = [holeCenterFirst, center]
    measurementPointNormals = [null, null]
    holeCenterFirst = null
    updateMeasurementGraphics()
    return
  }
  if (hits.length === 0) {
    logger.info('Viewer3D', 'Клик в режиме измерений: луч не попал в модель (hits.length === 0)')
    if (measurementPoints.length >= 2) clearMeasurements()
    return
  }
  const hit = hits[0]
  const mesh = hit.object as THREE.Mesh
  const worldNormal = hit.face!.normal.clone().transformDirection(mesh.matrixWorld).normalize()
  const candidates = getSnapCandidates(hit)
  const closest = getClosestSnapPoint(candidates, camera, mouse)
  const point = (closest ?? getPointFromHit(hit)).clone()
  if (measurementPoints.length >= 2) {
    clearMeasurements()
    measurementPoints = [point]
    measurementPointNormals = [worldNormal]
  } else {
    measurementPoints.push(point)
    const normalToPush = worldNormal ?? (measurementPointNormals.length > 0 ? measurementPointNormals[0] : null)
    measurementPointNormals.push(normalToPush)
    logger.info('Viewer3D', `Точка измерения добавлена (distance), всего точек: ${measurementPoints.length}`)
  }
  if (measurementPoints.length === 2 || measurementPoints.length === 3) {
    updateMeasurementGraphics()
  }
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
let firstClickHole: { center: THREE.Vector3; radius: number; normal: THREE.Vector3 } | null = null
let secondHoleResult: { center: THREE.Vector3; radius: number; normal: THREE.Vector3 } | null = null
let diameterSecondLabelEl: HTMLDivElement | null = null

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
  if (measureType !== 'distance' && measureType !== 'hole-center-distance' && !(measureType === 'diameter' && measurementPoints.length === 2)) return
  if (measurementPoints.length === 3) {
    const [p0, p1, p2] = measurementPoints
    const segs = [
      { a: p0, b: p1, color: AXIS_COLOR_X },
      { a: p1, b: p2, color: AXIS_COLOR_Y },
      { a: p2, b: p0, color: AXIS_COLOR_Z },
    ]
    for (const seg of segs) {
      const geom = new THREE.BufferGeometry().setFromPoints([seg.a, seg.b])
      const mat = new THREE.LineBasicMaterial({ color: seg.color })
      const line = new THREE.Line(geom, mat)
      measureGroup.add(line)
      measurementTriangleLines.push(line)
    }
    return
  }
  if (measurementPoints.length !== 2) return
  const [A, B] = measurementPoints
  if (measureType === 'hole-center-distance') {
    const geom = new THREE.BufferGeometry().setFromPoints([A, B])
    const mat = new THREE.LineBasicMaterial({ color: AXIS_COLOR_X })
    measurementLine = new THREE.Line(geom, mat)
    measureGroup.add(measurementLine)
    return
  }
  {
    const delta = B.clone().sub(A)
    const perpComp = MEASURE_PLANE_NORMAL.clone().multiplyScalar(delta.dot(MEASURE_PLANE_NORMAL))
    const Bprime = B.clone().sub(perpComp)
    const segs = [
      { a: A, b: B, color: AXIS_COLOR_X },
      { a: A, b: Bprime, color: AXIS_COLOR_Y },
      { a: Bprime, b: B, color: AXIS_COLOR_Z },
    ]
    for (const seg of segs) {
      const geom = new THREE.BufferGeometry().setFromPoints([seg.a, seg.b])
      const mat = new THREE.LineBasicMaterial({ color: seg.color })
      const line = new THREE.Line(geom, mat)
      measureGroup.add(line)
      measurementTriangleLines.push(line)
    }
    const nA = measurementPointNormals[0] ?? null
    const nB = measurementPointNormals[1] ?? null
    let basePoint: THREE.Vector3 | null = null
    let baseNormal: THREE.Vector3 | null = null
    let otherPoint: THREE.Vector3 | null = null
    if (nB) {
      basePoint = B
      baseNormal = nB.clone().normalize()
      otherPoint = A
    } else if (nA) {
      basePoint = A
      baseNormal = nA.clone().normalize()
      otherPoint = B
    }
    if (basePoint && baseNormal && otherPoint) {
      const v = otherPoint.clone().sub(basePoint)
      const distSigned = v.dot(baseNormal)
      const proj = otherPoint.clone().sub(baseNormal.clone().multiplyScalar(distSigned))
      const perpGeom = new THREE.BufferGeometry().setFromPoints([otherPoint, proj])
      const perpMat = new THREE.LineBasicMaterial({ color: 0xffff00 })
      measurementPerpLine = new THREE.Line(perpGeom, perpMat)
      measureGroup.add(measurementPerpLine)
    }
  }
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
  firstClickHole = null
  secondHoleResult = null
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
  if (!enabled) clearMeasurements()
  logger.info('Viewer3D', `Режим измерения: ${enabled ? 'вкл' : 'выкл'}`)
}

function setMeasureSnapMode(mode: MeasureSnapMode) {
  measureSnapMode = mode
}

function getMeasureSnapMode(): MeasureSnapMode {
  return measureSnapMode
}

function setMeasureType(type: MeasureType) {
  measureType = type
  if (type !== 'distance') {
    measurementPoints = []
    measurementPointNormals = []
  }
  radiusOrDiameterResult = null
  arcResult = null
  arcFirstPoint = null
  arcMesh = null
  holeCenterFirst = null
  firstClickHole = null
  secondHoleResult = null
  updateMeasurementGraphics()
}

/** Snap candidates for one triangle: 3 vertices, face center, 3 edge midpoints (world). Filtered by measureSnapMode. */
function getSnapCandidates(hit: THREE.Intersection): THREE.Vector3[] {
  const mesh = hit.object as THREE.Mesh
  const face = hit.face!
  const pos = mesh.geometry.attributes.position
  if (!pos) return [hit.point.clone()]
  const vA = new THREE.Vector3(pos.getX(face.a), pos.getY(face.a), pos.getZ(face.a)).applyMatrix4(mesh.matrixWorld)
  const vB = new THREE.Vector3(pos.getX(face.b), pos.getY(face.b), pos.getZ(face.b)).applyMatrix4(mesh.matrixWorld)
  const vC = new THREE.Vector3(pos.getX(face.c), pos.getY(face.c), pos.getZ(face.c)).applyMatrix4(mesh.matrixWorld)
  const center = vA.clone().add(vB).add(vC).multiplyScalar(1 / 3)
  const midAB = vA.clone().add(vB).multiplyScalar(0.5)
  const midBC = vB.clone().add(vC).multiplyScalar(0.5)
  const midCA = vC.clone().add(vA).multiplyScalar(0.5)
  if (measureSnapMode === 'vertex') return [vA, vB, vC]
  if (measureSnapMode === 'face') return [center]
  if (measureSnapMode === 'edge') return [midAB, midBC, midCA]
  if (measureSnapMode === 'intersection') return [hit.point.clone()]
  return [vA, vB, vC, center, midAB, midBC, midCA]
}

/** Pick candidate closest to cursor in NDC (within threshold). */
function getClosestSnapPoint(candidates: THREE.Vector3[], cam: THREE.Camera, mouseNDC: THREE.Vector2): THREE.Vector3 | null {
  let best: THREE.Vector3 | null = null
  let bestD = SNAP_SCREEN_THRESHOLD
  for (const p of candidates) {
    snapProj.copy(p).project(cam)
    const dx = snapProj.x - mouseNDC.x
    const dy = snapProj.y - mouseNDC.y
    const d = Math.sqrt(dx * dx + dy * dy)
    if (d < bestD) {
      bestD = d
      best = p
    }
  }
  return best
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
  logger.info('Viewer3D', `STL загружен: ${geometry.attributes.position?.count ?? 0} вершин, габариты ${size.x.toFixed(0)}×${size.y.toFixed(0)}×${size.z.toFixed(0)}`)
  console.log(`${LOG_PREFIX} STL: габариты модели ${size.x.toFixed(1)} x ${size.y.toFixed(1)} x ${size.z.toFixed(1)}, центрирование камеры`)
  centerModel(box)
}

const LOG_PREFIX = '[Viewer3D]'

function handleFile(file: File) {
  const ext = (file.name.split('.').pop() || '').toLowerCase()
  logger.info('Viewer3D', `Загрузка модели: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`)
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
          logger.info('Viewer3D', `Модель загружена: ${file.name} за ${(totalMs / 1000).toFixed(2)} с`)
          console.log(`${LOG_PREFIX} Модель загружена. Всего: ${(totalMs / 1000).toFixed(2)} с`)
        })
        .catch((err) => {
          logger.error('Viewer3D', `Ошибка загрузки STEP/IGES: ${file.name}`, err)
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
    const container = containerRef.value
    const labelEls = [
      measurementLabelEl,
      measurementLabelEl0,
      measurementLabelEl1,
      measurementLabelEl2,
      measurementPerpLabelEl,
      measurementExtraLabelEl,
      diameterSecondLabelEl,
    ].filter(Boolean) as HTMLDivElement[]
    const hasVisibleLabels = labelEls.some((el) => el.style.display !== 'none' && (el.textContent || '').trim())
    if (!container || !hasVisibleLabels) {
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
    const scaleX = canvas.width / canvasRect.width
    const scaleY = canvas.height / canvasRect.height
    for (const el of labelEls) {
      if (el.style.display === 'none') continue
      const text = (el.textContent || '').trim()
      if (!text) continue
      const r = el.getBoundingClientRect()
      const x = (r.left - canvasRect.left) * scaleX
      const y = (r.top - canvasRect.top) * scaleY
      const style = getComputedStyle(el)
      ctx.font = style.font
      ctx.fillStyle = style.color
      ctx.textBaseline = 'top'
      const padding = 2
      const bg = style.backgroundColor
      if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
        const m = ctx.measureText(text)
        ctx.fillStyle = bg
        ctx.fillRect(x - padding, y - padding, m.width + padding * 2, parseFloat(style.fontSize) || 14 + padding * 2)
        ctx.fillStyle = style.color
      }
      ctx.fillText(text, x, y)
    }
    resolve(canvas.toDataURL('image/png'))
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
  getOpenCascade().then(() => {
    console.log(`${LOG_PREFIX} WASM предзагружен (первый STEP/IGES откроется быстрее)`)
  })
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  if (containerRef.value) {
    containerRef.value.removeEventListener('mousemove', onContainerMouseMove, false)
  }
  if (renderer?.domElement) {
    renderer.domElement.removeEventListener('click', onCanvasClick)
    renderer.domElement.removeEventListener('mousedown', onCanvasMouseDown, true)
    renderer.domElement.removeEventListener('mousemove', onCanvasMouseMove, false)
    renderer.domElement.removeEventListener('mousemove', onCanvasMouseMovePan, true)
    renderer.domElement.removeEventListener('mouseup', onCanvasMouseUp, true)
    window.removeEventListener('mouseup', onCanvasMouseUp, true)
    renderer.domElement.removeEventListener('wheel', onCanvasWheel)
  }
  while (highlightGroup?.children.length) {
    const c = highlightGroup.children[0]
    highlightGroup.remove(c)
    if ('geometry' in c && c.geometry) c.geometry.dispose()
    if ('material' in c && c.material) (c.material as THREE.Material).dispose()
  }
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

function getMeasurementReport():
  | { length: number; dx: number; dy: number; dz: number }
  | { triangle: true; lengths: [number, number, number] }
  | null {
  if (measurementPoints.length === 2) {
    const p0 = measurementPoints[0]
    const p1 = measurementPoints[1]
    return {
      length: p0.distanceTo(p1),
      dx: p1.x - p0.x,
      dy: p1.y - p0.y,
      dz: p1.z - p0.z,
    }
  }
  if (measurementPoints.length === 3) {
    const p0 = measurementPoints[0]
    const p1 = measurementPoints[1]
    const p2 = measurementPoints[2]
    return {
      triangle: true,
      lengths: [
        p0.distanceTo(p1),
        p1.distanceTo(p2),
        p2.distanceTo(p0),
      ],
    }
  }
  return null
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
  setMeasureType,
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
