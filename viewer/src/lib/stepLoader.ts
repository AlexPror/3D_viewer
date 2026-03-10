/**
 * Загрузка STEP/IGES через opencascade.js.
 * STEP: XCAF — детали по меткам, цвета, метизы отдельным цветом. IGES: один shape → GLB.
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

/** false = быстрый путь (STEPControl_Reader), true = пробовать XCAF (дольше, у твоих файлов детали не находятся). */
const ENABLE_XCAF_GEOMETRY = false

function getInputPath(ext: string): string {
  if (ext === 'step' || ext === 'stp') return '/input.stp'
  if (ext === 'igs' || ext === 'iges') return '/input.igs'
  return '/input.stp'
}

/** Отклонение линейное (мм): больше = быстрее тесселяция, грубее сетка. 1.0 — компромисс скорости и качества. */
const LINEAR_DEFLECTION = 1.0
const ANGULAR_DEFLECTION = 0.5

/** Ключевые слова в имени детали для определения метизов (рус. + англ.) */
const METIZ_KEYWORDS = [
  'болт', 'гайка', 'винт', 'шайба', 'крепеж', 'шуруп', 'саморез', 'заклепка', 'штифт', 'шпилька',
  'bolt', 'nut', 'screw', 'washer', 'fastener', 'din ', 'iso ', 'pin', 'rivet', 'stud', 'hex',
]

function isMetizByName(name: string): boolean {
  const lower = (name || '').toLowerCase()
  return METIZ_KEYWORDS.some((kw) => lower.includes(kw))
}

/** Палитра RGB (0..1) для лога и запасной вариант. Одинаковое имя → один цвет. */
const NAME_PALETTE_RGB: [number, number, number][] = [
  [0.25, 0.45, 0.85], [0.85, 0.35, 0.25], [0.25, 0.65, 0.45], [0.85, 0.65, 0.2],
  [0.55, 0.35, 0.75], [0.35, 0.75, 0.85], [0.9, 0.5, 0.5], [0.4, 0.8, 0.5],
  [0.75, 0.5, 0.85], [0.6, 0.6, 0.3], [0.3, 0.6, 0.8], [0.9, 0.6, 0.35],
  [0.5, 0.5, 0.75], [0.7, 0.8, 0.4], [0.45, 0.7, 0.7], [0.8, 0.4, 0.6],
]

/** Именованные цвета OCCT (Quantity_NameOfColor) для палитры — конструктор Quantity_Color(enum) доступен в биндингах. */
const NOC_PALETTE_KEYS = [
  'Quantity_NOC_BLUE1', 'Quantity_NOC_RED1', 'Quantity_NOC_GREEN1', 'Quantity_NOC_ORANGE1',
  'Quantity_NOC_VIOLET', 'Quantity_NOC_CYAN1', 'Quantity_NOC_TOMATO', 'Quantity_NOC_SPRINGGREEN',
  'Quantity_NOC_PURPLE', 'Quantity_NOC_OLIVEDRAB', 'Quantity_NOC_SKYBLUE', 'Quantity_NOC_SALMON',
  'Quantity_NOC_MEDIUMBLUE', 'Quantity_NOC_LIGHTGREEN', 'Quantity_NOC_LIGHTCYAN', 'Quantity_NOC_MAGENTA1',
]
const NOC_METIZ = 'Quantity_NOC_GRAY75'

/** Детерминированный индекс цвета по имени (одинаковое имя → один и тот же цвет). */
function getColorIndexForName(name: string): number {
  let h = 0
  const s = name || '\0'
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0
  return Math.abs(h) % NOC_PALETTE_KEYS.length
}

/** RGB 0..1 → hex #rrggbb для лога. */
function rgbToHex(r: number, g: number, b: number): string {
  const toByte = (x: number) => Math.round(Math.max(0, Math.min(1, x)) * 255)
  return '#' + [toByte(r), toByte(g), toByte(b)].map((n) => n.toString(16).padStart(2, '0')).join('')
}

/** Создать Quantity_Color через именованный цвет (enum), т.к. конструктор от RGB в биндингах недоступен. */
function createQuantityColor(oc: any, nocKey: string): any {
  const noc = oc[nocKey]
  if (noc === undefined) return null
  return new oc.Quantity_Color(noc)
}

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

/** Строка из OCCT часто приходит как UTF-8 байты, прочитанные как Latin-1 — передекодируем в UTF-8. */
function decodeUtf8FromLatin1(raw: string): string {
  if (!raw || typeof raw !== 'string') return ''
  try {
    const bytes = new Uint8Array([...raw].map((c) => c.charCodeAt(0) & 0xff))
    return new TextDecoder('utf-8').decode(bytes)
  } catch {
    return raw
  }
}

/** Получить имя продукта по метке XCAF (TDataStd_Name). */
function getLabelName(oc: any, label: any): string {
  try {
    const att = new oc.Handle_TDF_Attribute_2(new oc.TDataStd_Name())
    if (!label.FindAttribute_1(oc.TDataStd_Name.GetID(), att)) return ''
    const extStr = att.get().Get()
    const asciiStr = new oc.TCollection_AsciiString_13(extStr, 0)
    const str = asciiStr.ToCString ? asciiStr.ToCString() : ''
    const s = typeof str === 'string' ? str : ''
    return decodeUtf8FromLatin1(s)
  } catch {
    return ''
  }
}


/** Имя по цепочке referred до конечной метки определения (имя детали, а не сборки). */
function getLabelNameFollowingRefs(oc: any, shapeTool: any, label: any): string {
  const ref1 = new oc.TDF_Label()
  const ref2 = new oc.TDF_Label()
  let cur = label
  for (let depth = 0; depth < 50; depth++) {
    const out = depth % 2 === 0 ? ref1 : ref2
    const hasRef = shapeToolInvoke(shapeTool, 'GetReferredShape', cur, out) === true
    if (!hasRef) break
    cur = out
  }
  return getLabelName(oc, cur)
}

/** Результат обхода: имя детали, признак метиза и присвоенный цвет (для лога). */
export type PartInfo = { name: string; isMetiz: boolean; color: string }

/** Вызов метода ShapeTool с учётом суффиксов биндингов (_1 и т.д.). */
function shapeToolInvoke(shapeTool: any, methodBase: string, ...args: any[]): any {
  const fn = shapeTool[`${methodBase}_1`] ?? shapeTool[methodBase]
  if (typeof fn !== 'function') return undefined
  return fn.apply(shapeTool, args)
}

/** Обход всех меток под label через TDF_ChildIterator (allLevels=true) и меширование каждой с формой. */
function visitLabelsWithChildIterator(
  oc: any,
  label: any,
  shapeTool: any,
  colorTool: any,
  metizColor: any,
  colorType: number,
  partNames: PartInfo[]
): void {
  const ChildIterator = oc.TDF_ChildIterator_2 ?? oc.TDF_ChildIterator_1 ?? oc.TDF_ChildIterator
  if (typeof ChildIterator !== 'function') return
  const it = new ChildIterator(label, true)
  if (!it || typeof it.More !== 'function') return
  while (it.More()) {
    const childLabel = it.Value()
    const shape = shapeToolInvoke(shapeTool, 'GetShape', childLabel)
    if (shape && !shape.IsNull()) {
      new oc.BRepMesh_IncrementalMesh_2(shape, LINEAR_DEFLECTION, false, ANGULAR_DEFLECTION, false)
      const name = getLabelName(oc, childLabel)
      const isMetiz = isMetizByName(name)
      const [r, g, b] = isMetiz ? [0.72, 0.72, 0.75] : NAME_PALETTE_RGB[getColorIndexForName(name)]
      partNames.push({ name: name || '(без имени)', isMetiz, color: rgbToHex(r, g, b) })
      const partColor = isMetiz ? metizColor : createQuantityColor(oc, NOC_PALETTE_KEYS[getColorIndexForName(name)])
      if (partColor) colorTool.SetColor(childLabel, partColor, colorType)
    }
    it.Next()
  }
}

/** Рекурсивно обойти метки: для каждой с геометрией — мешить и задать цвет (метизы — свой, остальные — по названию). */
function visitLabels(
  oc: any,
  label: any,
  shapeTool: any,
  colorTool: any,
  metizColor: any,
  colorType: number,
  partNames: PartInfo[]
): void {
  const shape = shapeToolInvoke(shapeTool, 'GetShape', label)
  const components = new oc.TDF_LabelSequence_1()
  shapeToolInvoke(shapeTool, 'GetComponents', label, components, false)
  const hasComponents = components.Length() > 0
  const referred = new oc.TDF_Label()
  const hasReferred = !hasComponents && shapeToolInvoke(shapeTool, 'GetReferredShape', label, referred) === true

  if (shape && !shape.IsNull()) {
    new oc.BRepMesh_IncrementalMesh_2(shape, LINEAR_DEFLECTION, false, ANGULAR_DEFLECTION, false)
    const name = getLabelName(oc, label)
    const isMetiz = isMetizByName(name)
    const [r, g, b] = isMetiz ? [0.72, 0.72, 0.75] : NAME_PALETTE_RGB[getColorIndexForName(name)]
    partNames.push({ name: name || '(без имени)', isMetiz, color: rgbToHex(r, g, b) })
    const partColor = isMetiz ? metizColor : createQuantityColor(oc, NOC_PALETTE_KEYS[getColorIndexForName(name)])
    if (partColor) colorTool.SetColor(label, partColor, colorType)
  } else if (hasReferred) {
    visitLabels(oc, referred, shapeTool, colorTool, metizColor, colorType, partNames)
    const name = getLabelName(oc, referred)
    const isMetiz = isMetizByName(name)
    const partColor = isMetiz ? metizColor : createQuantityColor(oc, NOC_PALETTE_KEYS[getColorIndexForName(name)])
    if (partColor) colorTool.SetColor(label, partColor, colorType)
  }

  if (hasComponents) {
    for (let i = 1; i <= components.Length(); i++) {
      visitLabels(oc, components.Value(i), shapeTool, colorTool, metizColor, colorType, partNames)
    }
  }
}

/**
 * Загрузка STEP через XCAF: детали по меткам, цвета из файла, метизы — отдельным цветом.
 * Без UpdateAssembly(). При ошибке XCAF — откат на один shape (STEPControl_Reader).
 */
async function loadStepXcafToGlbUrl(oc: any, filename: string): Promise<string> {
  const tXcaf = performance.now()
  console.log(`${LOG_PREFIX} XCAF: создание документа и ридера...`)
  const doc = new oc.TDocStd_Document(new oc.TCollection_ExtendedString_1())
  const docHandle = new oc.Handle_TDocStd_Document_2(doc)

  const reader = new oc.STEPCAFControl_Reader_1()
  reader.SetColorMode(true)
  reader.SetNameMode(true)
  reader.ReadFile(filename)
  console.log(`${LOG_PREFIX} XCAF: ReadFile готов, Transfer_1...`)
  const tTransfer = performance.now()
  reader.Transfer_1(docHandle, new oc.Message_ProgressRange_1())
  console.log(`${LOG_PREFIX} XCAF: Transfer_1 готов за ${((performance.now() - tTransfer) / 1000).toFixed(2)} с`)

  const mainLabel = docHandle.get().Main()
  const shapeTool = oc.XCAFDoc_DocumentTool.ShapeTool(mainLabel).get()
  const colorTool = oc.XCAFDoc_DocumentTool.ColorTool(mainLabel).get()
  console.log(`${LOG_PREFIX} XCAF: ShapeTool/ColorTool получены`)

  const metizColor = createQuantityColor(oc, NOC_METIZ) ?? createQuantityColor(oc, 'Quantity_NOC_GRAY80') ?? createQuantityColor(oc, 'Quantity_NOC_WHITE')
  if (!metizColor) {
    console.warn(`${LOG_PREFIX} Quantity_Color в биндингах недоступен — XCAF без раскраски деталей`)
  }
  const colorType = oc.XCAFDoc_ColorGen

  const freeShapes = new oc.TDF_LabelSequence_1()
  shapeToolInvoke(shapeTool, 'GetFreeShapes', freeShapes)
  const numRoots = freeShapes.Length()
  console.log(`${LOG_PREFIX} XCAF: GetFreeShapes готов, корневых меток: ${numRoots}, обход и тесселяция...`)
  const tVisit = performance.now()
  const partNames: PartInfo[] = []
  let partCount = 0
  for (let i = 1; i <= numRoots; i++) {
    visitLabels(oc, freeShapes.Value(i), shapeTool, colorTool, metizColor, colorType, partNames)
    partCount++
    if (i <= 3 || i === numRoots) {
      console.log(`${LOG_PREFIX} XCAF: обработана метка ${i}/${numRoots}, деталей с геометрией: ${partNames.length}`)
    }
  }
  if (partNames.length === 0 && numRoots > 0) {
    console.log(`${LOG_PREFIX} XCAF: обход по GetComponents не нашёл форм — пробуем TDF_ChildIterator...`)
    for (let i = 1; i <= numRoots; i++) {
      visitLabelsWithChildIterator(oc, freeShapes.Value(i), shapeTool, colorTool, metizColor, colorType, partNames)
    }
    console.log(`${LOG_PREFIX} XCAF: после ChildIterator деталей с геометрией: ${partNames.length}`)
  }
  if (partNames.length === 0) {
    const nodeNames: string[] = []
    for (let i = 1; i <= numRoots; i++) {
      const rootLabel = freeShapes.Value(i)
      const rootName = getLabelNameFollowingRefs(oc, shapeTool, rootLabel) || getLabelName(oc, rootLabel) || `(корень ${i})`
      nodeNames.push(rootName)
      const compSeq = new oc.TDF_LabelSequence_1()
      shapeToolInvoke(shapeTool, 'GetComponents', rootLabel, compSeq, true)
      if (compSeq.Length() > 0) {
        for (let k = 1; k <= compSeq.Length(); k++) {
          const compLabel = compSeq.Value(k)
          const name = getLabelNameFollowingRefs(oc, shapeTool, compLabel) || getLabelName(oc, compLabel)
          if (name) nodeNames.push(name)
        }
      } else {
        const ChildIterator = oc.TDF_ChildIterator_2 ?? oc.TDF_ChildIterator_1 ?? oc.TDF_ChildIterator
        if (typeof ChildIterator === 'function') {
          const it = new ChildIterator(rootLabel, true)
          if (it && typeof it.More === 'function') {
            while (it.More()) {
              const childLabel = it.Value()
              const name = getLabelNameFollowingRefs(oc, shapeTool, childLabel) || getLabelName(oc, childLabel)
              if (name) nodeNames.push(name)
              it.Next()
            }
          }
        }
      }
    }
    const uniqueNames = [...new Set(nodeNames)]
    void uniqueNames
    // Отладочный вывод по PRODUCT/XCAF отключён: теперь используем серверные метаданные.
    throw new Error('XCAF: не найдено форм для тесселяции — откат на один shape')
  }
  console.log(`${LOG_PREFIX} XCAF: обход готов за ${((performance.now() - tVisit) / 1000).toFixed(2)} с, всего: ${partCount} корневых, ${partNames.length} деталей с геометрией`)
  if (partNames.length > 0) {
    console.log(`${LOG_PREFIX} Найденные детали (название | метиз | цвет):`)
    partNames.forEach((p, idx) => {
      console.log(`  ${idx + 1}. ${p.name} ${p.isMetiz ? '(метиз)' : ''} — ${p.color}`)
    })
  }

  const tExport = performance.now()
  const glbPath = new oc.TCollection_AsciiString_2(GLB_PATH)
  const writer = new oc.RWGltf_CafWriter(glbPath, true)
  const fileInfo = new oc.TColStd_IndexedDataMapOfStringString_1()
  const progress = new oc.Message_ProgressRange_1()
  const ok = writer.Perform_2(docHandle, fileInfo, progress)
  if (!ok) throw new Error('RWGltf_CafWriter.Perform_2 вернул false')
  console.log(`${LOG_PREFIX} XCAF: экспорт GLB готов за ${((performance.now() - tExport) / 1000).toFixed(2)} с, всего XCAF: ${((performance.now() - tXcaf) / 1000).toFixed(2)} с`)

  const glbData = oc.FS.readFile(GLB_PATH, { encoding: 'binary' })
  if (!glbData || !glbData.buffer || glbData.byteLength === 0) {
    throw new Error('GLB файл пустой или не найден в FS')
  }
  return URL.createObjectURL(new Blob([glbData.buffer], { type: 'model/gltf-binary' }))
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
    if (ENABLE_XCAF_GEOMETRY) {
      try {
        url = await loadStepXcafToGlbUrl(oc, filename)
        console.log(`${LOG_PREFIX} чтение XCAF + перенос: ${((performance.now() - tTransfer) / 1000).toFixed(2)} с`)
      } catch (xcafErr) {
        console.warn(`${LOG_PREFIX} XCAF не удался, используем один shape:`, xcafErr)
        const reader = new oc.STEPControl_Reader_1()
        reader.ReadFile(filename)
        const progress = new oc.Message_ProgressRange_1()
        reader.TransferRoots(progress)
        const shape = reader.OneShape()
        console.log(`${LOG_PREFIX} чтение + перенос: ${((performance.now() - tTransfer) / 1000).toFixed(2)} с`)
        if (!shape || shape.IsNull()) throw new Error('Не удалось получить геометрию')
        url = shapeToGlbUrl(oc, shape)
      }
    } else {
      const reader = new oc.STEPControl_Reader_1()
      reader.ReadFile(filename)
      const progress = new oc.Message_ProgressRange_1()
      reader.TransferRoots(progress)
      const shape = reader.OneShape()
      console.log(`${LOG_PREFIX} чтение + перенос: ${((performance.now() - tTransfer) / 1000).toFixed(2)} с`)
      if (!shape || shape.IsNull()) throw new Error('Не удалось получить геометрию')
      url = shapeToGlbUrl(oc, shape)
    }
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
