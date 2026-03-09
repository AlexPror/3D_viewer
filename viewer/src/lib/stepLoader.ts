/**
 * Загрузка STEP/IGES через opencascade.js: чтение файла → один shape → тесселяция → экспорт в GLB → Object URL.
 * WASM подгружается по ?url, чтобы Vite не бандлил бинарник.
 */
const LOG_PREFIX = '[stepLoader]'

let ocPromise: Promise<any> | null = null

export function getOpenCascade(): Promise<any> {
  if (!ocPromise) {
    console.log(`${LOG_PREFIX} Инициализация opencascade.js (WASM)...`)
    ocPromise = (async () => {
      const [mod, wasmModule] = await Promise.all([
        import('opencascade.js/dist/opencascade.full.js'),
        import('opencascade.js/dist/opencascade.full.wasm?url'),
      ])
      const Module = mod.default as (opts?: { locateFile?: (path: string) => string }) => Promise<any>
      const wasmUrl = (wasmModule as { default: string }).default
      return Module({
        locateFile: (path: string) => (path.endsWith('.wasm') ? wasmUrl : path),
      })
    })()
    ocPromise.then(() => console.log(`${LOG_PREFIX} opencascade.js готов`))
  }
  return ocPromise
}

const GLB_PATH = '/output.glb'

function getInputPath(ext: string): string {
  if (ext === 'step' || ext === 'stp') return '/input.stp'
  if (ext === 'igs' || ext === 'iges') return '/input.igs'
  return '/input.stp'
}

const LINEAR_DEFLECTION = 0.5
const ANGULAR_DEFLECTION = 0.5

/**
 * Преобразует один shape в GLB и возвращает Object URL (нужно вызвать URL.revokeObjectURL после загрузки).
 * Логирует время тесселяции и экспорта в GLB.
 */
function shapeToGlbUrl(oc: any, shape: any, timings?: { tessellateMs: number; exportMs: number }): string {
  try {
    const doc = new oc.TDocStd_Document(new oc.TCollection_ExtendedString_1())
    const docHandle = new oc.Handle_TDocStd_Document_2(doc)
    const mainLabel = docHandle.get().Main()
    const shapeTool = oc.XCAFDoc_DocumentTool.ShapeTool(mainLabel).get()
    const label = shapeTool.NewShape()
    shapeTool.SetShape(label, shape)

    const tTess = performance.now()
    new oc.BRepMesh_IncrementalMesh_2(shape, LINEAR_DEFLECTION, false, ANGULAR_DEFLECTION, false)
    const tessellateMs = performance.now() - tTess
    if (timings) timings.tessellateMs = tessellateMs
    console.log(`${LOG_PREFIX} тесселяция: ${(tessellateMs / 1000).toFixed(2)} с`)

    const tExport = performance.now()
    const glbPath = new oc.TCollection_AsciiString_2(GLB_PATH)
    const writer = new oc.RWGltf_CafWriter(glbPath, true)
    const fileInfo = new oc.TColStd_IndexedDataMapOfStringString_1()
    const progress = new oc.Message_ProgressRange_1()
    const ok = writer.Perform_2(docHandle, fileInfo, progress)
    if (!ok) {
      throw new Error('RWGltf_CafWriter.Perform_2 вернул false')
    }
    const exportMs = performance.now() - tExport
    if (timings) timings.exportMs = exportMs
    console.log(`${LOG_PREFIX} экспорт GLB: ${(exportMs / 1000).toFixed(2)} с`)

    const glbData = oc.FS.readFile(GLB_PATH, { encoding: 'binary' })
    if (!glbData || !glbData.buffer || glbData.byteLength === 0) {
      throw new Error('GLB файл пустой или не найден в FS')
    }
    return URL.createObjectURL(new Blob([glbData.buffer], { type: 'model/gltf-binary' }))
  } catch (e) {
    console.error(`${LOG_PREFIX} shapeToGlbUrl ошибка:`, e)
    if (e instanceof Error) {
      console.error(`${LOG_PREFIX} message:`, e.message, 'stack:', e.stack)
    } else {
      console.error(`${LOG_PREFIX} (не Error):`, String(e), JSON.stringify(e, null, 2))
    }
    throw e
  }
}

/**
 * Читает STEP или IGES из ArrayBuffer, возвращает Object URL GLB-файла.
 * В консоль выводит тайминги по этапам: WASM, чтение+перенос, тесселяция, экспорт.
 */
export async function loadStepOrIgesToGlbUrl(
  arrayBuffer: ArrayBuffer,
  extension: string
): Promise<string> {
  const tTotal = performance.now()

  const tWasm = performance.now()
  const oc = await getOpenCascade()
  console.log(`${LOG_PREFIX} WASM готов: ${((performance.now() - tWasm) / 1000).toFixed(2)} с`)

  const ext = extension.toLowerCase()
  if (ext === 'dxf') {
    console.warn(`${LOG_PREFIX} DXF пока не поддерживается`)
    throw new Error('Формат DXF пока не поддерживается')
  }

  const filename = getInputPath(ext)
  oc.FS.writeFile(filename, new Uint8Array(arrayBuffer))
  console.log(`${LOG_PREFIX} Файл записан в FS: ${filename}, размер ${arrayBuffer.byteLength}`)

  const tTransfer = performance.now()
  let url: string

  if (ext === 'step' || ext === 'stp') {
    const reader = new oc.STEPControl_Reader_1()
    reader.ReadFile(filename)
    const progress = new oc.Message_ProgressRange_1()
    reader.TransferRoots(progress)
    const shape = reader.OneShape()
    console.log(`${LOG_PREFIX} чтение + перенос: ${((performance.now() - tTransfer) / 1000).toFixed(2)} с`)
    if (!shape || shape.IsNull()) throw new Error('Не удалось получить геометрию')
    url = shapeToGlbUrl(oc, shape)
  } else if (ext === 'igs' || ext === 'iges') {
    const reader = new oc.IGESControl_Reader_1()
    const readStatus = reader.ReadFile(filename)
    console.log(`${LOG_PREFIX} ReadFile статус:`, readStatus)
    const progress = new oc.Message_ProgressRange_1()
    reader.TransferRoots(progress)
    const shape = reader.OneShape()
    console.log(`${LOG_PREFIX} чтение + перенос: ${((performance.now() - tTransfer) / 1000).toFixed(2)} с`)
    if (!shape || shape.IsNull()) throw new Error('Не удалось получить геометрию из файла')
    url = shapeToGlbUrl(oc, shape)
  } else {
    throw new Error(`Неизвестное расширение: ${extension}`)
  }

  console.log(
    `${LOG_PREFIX} конвертация STEP/IGES→GLB всего: ${((performance.now() - tTotal) / 1000).toFixed(2)} с`
  )
  return url
}
