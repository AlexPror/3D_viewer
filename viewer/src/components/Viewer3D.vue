<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import * as THREE from 'three'
import { TrackballControls } from 'three/addons/controls/TrackballControls.js'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { loadStepOrIgesToGlbUrl, getOpenCascade } from '../lib/stepLoader'

const containerRef = ref<HTMLDivElement | null>(null)
const isLoading = ref(false)

let scene: THREE.Scene
let camera: THREE.PerspectiveCamera
let renderer: THREE.WebGLRenderer
let controls: InstanceType<typeof TrackballControls>
let meshGroup: THREE.Group
let animationId: number
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
  containerRef.value.appendChild(renderer.domElement)

  controls = new TrackballControls(camera, renderer.domElement)
  controls.rotateSpeed = 6.4
  controls.zoomSpeed = 2.4
  controls.panSpeed = 2
  controls.staticMoving = false
  controls.dynamicDampingFactor = 0.15
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

  function animate() {
    animationId = requestAnimationFrame(animate)
    controls.update()
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
    if (ext === 'dxf') {
      console.warn('формат: DXF — пока не реализовано')
      console.groupEnd()
      return
    }
    console.warn('формат: неизвестный, расширение:', ext)
    console.groupEnd()
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

onMounted(() => {
  initScene()
  getOpenCascade().then(() => {
    console.log(`${LOG_PREFIX} WASM предзагружен (первый STEP/IGES откроется быстрее)`)
  })
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  if (animationId) cancelAnimationFrame(animationId)
  controls?.dispose()
  renderer?.dispose()
  if (containerRef.value && renderer?.domElement) {
    containerRef.value.removeChild(renderer.domElement)
  }
})

defineExpose({
  openFileDialog,
  takeScreenshot,
  getLoadedFileName: () => loadedFileName,
  resetView,
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
