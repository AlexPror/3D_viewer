/**
 * Загрузка STEP/IGES через opencascade.js.
 * STEP: XCAF — детали по меткам; цвет из STEP (ColorTool), иначе палитра по имени; метизы — серый. IGES: один shape → GLB.
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

/** false = быстрый путь (STEPControl_Reader), true = пробовать XCAF (дольше, но сохраняет/назначает цвета деталей при успехе). */
const ENABLE_XCAF_GEOMETRY = true

function getInputPath(ext: string): string {
  if (ext === 'step' || ext === 'stp') return '/input.stp'
  if (ext === 'igs' || ext === 'iges') return '/input.igs'
  return '/input.stp'
}

function tryUnlinkOcFs(oc: { FS?: { unlink: (path: string) => void } }, path: string): void {
  try {
    oc.FS?.unlink(path)
  } catch {
    /* файл мог не создаться */
  }
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

/** Quantity_Color из RGB 0..1 (предпочтительно для палитры). */
function createQuantityColorFromRgb(oc: any, r: number, g: number, b: number): any | null {
  const toc =
    oc.Quantity_TOC_RGB ??
    oc.Quantity_TypeOfColor?.Quantity_TOC_RGB ??
    oc.Quantity_TypeOfColor?.Quantity_TOC_sRGB
  if (toc !== undefined) {
    const ctors = [oc.Quantity_Color_4, oc.Quantity_Color_3, oc.Quantity_Color_2, oc.Quantity_Color_1, oc.Quantity_Color]
    for (const Ctor of ctors) {
      if (typeof Ctor !== 'function') continue
      try {
        return new Ctor(r, g, b, toc)
      } catch {
        try {
          return new Ctor(r, g, b)
        } catch {
          continue
        }
      }
    }
  }
  return null
}

/** Именованный Quantity_Color (enum NOC). */
function createQuantityColor(oc: any, nocKey: string): any | null {
  const noc = oc[nocKey]
  if (noc === undefined) return null
  try {
    return new oc.Quantity_Color(noc)
  } catch {
    try {
      return new oc.Quantity_Color_1(noc)
    } catch {
      return null
    }
  }
}

function createPartColor(oc: any, r: number, g: number, b: number, nocFallback: string): any | null {
  return createQuantityColorFromRgb(oc, r, g, b) ?? createQuantityColor(oc, nocFallback)
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
export type PartInfo = { name: string; isMetiz: boolean; color: string; colorSource: 'file' | 'metiz' | 'palette' }

/** Счётчики источников цвета при XCAF-обходе (для лога). */
export type XcafColorStats = { fromFile: number; palette: number; metiz: number }

const XCAF_COLOR_TYPES: Array<{ key: string; resolve: (oc: any) => number | undefined }> = [
  { key: 'ColorGen', resolve: (oc) => oc.XCAFDoc_ColorGen },
  { key: 'ColorSurf', resolve: (oc) => oc.XCAFDoc_ColorSurf },
  { key: 'ColorCurv', resolve: (oc) => oc.XCAFDoc_ColorCurv },
]

function quantityColorToRgb(qColor: any): [number, number, number] | null {
  if (!qColor) return null
  try {
    if (typeof qColor.Red === 'function') {
      return [qColor.Red(), qColor.Green(), qColor.Blue()]
    }
    if (typeof qColor.GetRGB === 'function') {
      const rgb = qColor.GetRGB()
      if (rgb && typeof rgb.Red === 'function') {
        return [rgb.Red(), rgb.Green(), rgb.Blue()]
      }
    }
  } catch {
    return null
  }
  return null
}

function colorToolHasColor(colorTool: any, label: any, colorType: number): boolean {
  for (const suffix of ['_2', '_1', '']) {
    const fn = colorTool[`IsSet${suffix}`]
    if (typeof fn === 'function') {
      try {
        if (fn.call(colorTool, label, colorType) === true) return true
      } catch {
        // next signature
      }
    }
  }
  return false
}

/** Прочитать RGB 0..1 из ColorTool, если цвет задан в STEP/XCAF после Transfer. */
function tryGetLabelRgbFromColorTool(
  oc: any,
  colorTool: any,
  label: any,
): [number, number, number] | null {
  for (const { resolve } of XCAF_COLOR_TYPES) {
    const colorType = resolve(oc)
    if (colorType === undefined) continue
    if (!colorToolHasColor(colorTool, label, colorType)) continue

    for (const suffix of ['_7', '_5', '_2', '_1', '']) {
      const fn = colorTool[`GetColor${suffix}`]
      if (typeof fn !== 'function') continue
      try {
        const qColor = new oc.Quantity_Color()
        let ok = false
        try {
          ok = fn.call(colorTool, label, qColor, colorType) === true
        } catch {
          try {
            ok = fn.call(colorTool, label, colorType, qColor) === true
          } catch {
            continue
          }
        }
        if (!ok) continue
        const rgb = quantityColorToRgb(qColor)
        if (rgb) return rgb
      } catch {
        continue
      }
    }
  }
  return null
}

type ResolvedLabelColor = {
  rgb: [number, number, number]
  colorSource: PartInfo['colorSource']
  /** Quantity_Color для SetColor; null — не перезаписывать (уже в файле). */
  partColor: any | null
}

function resolveLabelColor(
  oc: any,
  colorTool: any,
  label: any,
  name: string,
  metizColor: any,
  stats: XcafColorStats,
): ResolvedLabelColor {
  const fromFile = tryGetLabelRgbFromColorTool(oc, colorTool, label)
  if (fromFile) {
    stats.fromFile += 1
    return { rgb: fromFile, colorSource: 'file', partColor: null }
  }
  const isMetiz = isMetizByName(name)
  if (isMetiz) {
    stats.metiz += 1
    const rgb: [number, number, number] = [0.72, 0.72, 0.75]
    return {
      rgb,
      colorSource: 'metiz',
      partColor: metizColor ?? createPartColor(oc, ...rgb, NOC_METIZ),
    }
  }
  const idx = getColorIndexForName(name)
  stats.palette += 1
  const [r, g, b] = NAME_PALETTE_RGB[idx]
  return {
    rgb: [r, g, b],
    colorSource: 'palette',
    partColor: createPartColor(oc, r, g, b, NOC_PALETTE_KEYS[idx]),
  }
}

function applyResolvedColorToLabel(
  colorTool: any,
  label: any,
  colorType: number,
  resolved: ResolvedLabelColor,
): void {
  if (!resolved.partColor) return
  occtInvoke(colorTool, 'SetColor', label, resolved.partColor, colorType)
}

/** Вызов метода ShapeTool / ColorTool с перебором суффиксов биндингов. */
function occtInvoke(target: any, methodBase: string, ...args: any[]): any {
  const names: string[] = []
  for (const suffix of ['_1', '_2', '_3', '']) {
    names.push(suffix ? `${methodBase}${suffix}` : methodBase)
  }
  for (const name of names) {
    const fn = target[name]
    if (typeof fn !== 'function') continue
    try {
      return fn.apply(target, args)
    } catch {
      if (args.length > 1) {
        try {
          return fn.apply(target, args.slice(0, args.length - 1))
        } catch {
          continue
        }
      }
    }
  }
  return undefined
}

function shapeToolInvoke(shapeTool: any, methodBase: string, ...args: any[]): any {
  return occtInvoke(shapeTool, methodBase, ...args)
}

function updateXcafAssemblies(shapeTool: any): void {
  const r = shapeToolInvoke(shapeTool, 'UpdateAssemblies')
  if (r === undefined) {
    shapeToolInvoke(shapeTool, 'ComputeAssembly')
  }
}

function getShapeFromNamingAttribute(oc: any, label: any): any | null {
  try {
    const NamedShape = oc.TNaming_NamedShape
    if (!NamedShape?.GetID) return null
    const att = new oc.Handle_TDF_Attribute_2(new NamedShape())
    if (!label.FindAttribute_1(NamedShape.GetID(), att)) return null
    const named = att.get()
    if (!named) return null
    for (const getter of ['Get', 'GetShape', 'GetShape_1']) {
      const fn = named[getter]
      if (typeof fn !== 'function') continue
      const shape = fn.call(named)
      if (shape && !shape.IsNull()) return shape
    }
  } catch {
    return null
  }
  return null
}

function getShapeForLabel(shapeTool: any, label: any, oc: any): any | null {
  let shape = shapeToolInvoke(shapeTool, 'GetShape', label)
  if (shape && !shape.IsNull()) return shape
  shape = getShapeFromNamingAttribute(oc, label)
  if (shape && !shape.IsNull()) return shape
  const referred = new oc.TDF_Label()
  if (shapeToolInvoke(shapeTool, 'GetReferredShape', label, referred) === true) {
    shape = shapeToolInvoke(shapeTool, 'GetShape', referred)
    if (shape && !shape.IsNull()) return shape
    shape = getShapeFromNamingAttribute(oc, referred)
    if (shape && !shape.IsNull()) return shape
  }
  return null
}

function getChildLabels(oc: any, shapeTool: any, label: any): any[] {
  const out: any[] = []
  for (const expand of [true, false] as const) {
    const seq = new oc.TDF_LabelSequence_1()
    shapeToolInvoke(shapeTool, 'GetComponents', label, seq, expand)
    const n = seq.Length()
    if (n > 0) {
      for (let i = 1; i <= n; i++) out.push(seq.Value(i))
      return out
    }
  }
  const ChildIterator = oc.TDF_ChildIterator_2 ?? oc.TDF_ChildIterator_1 ?? oc.TDF_ChildIterator
  if (typeof ChildIterator === 'function') {
    const it = new ChildIterator(label, true)
    if (it && typeof it.More === 'function') {
      while (it.More()) {
        out.push(it.Value())
        it.Next()
      }
    }
  }
  return out
}

function tessellateShape(oc: any, shape: any): void {
  new oc.BRepMesh_IncrementalMesh_2(shape, LINEAR_DEFLECTION, false, ANGULAR_DEFLECTION, false)
}

/** Все метки с геометрией в XCAF-документе (КОМПАС/STEP). */
function collectAllShapeLabels(oc: any, shapeTool: any): any[] {
  const labels: any[] = []
  const seen = new Set<string>()

  const addLabel = (label: any) => {
    if (!label) return
    const tag = String(typeof label.Tag === 'function' ? label.Tag() : (label.Tag ?? ''))
    if (!tag || seen.has(tag)) return
    seen.add(tag)
    labels.push(label)
  }

  const shapesSeq = new oc.TDF_LabelSequence_1()
  shapeToolInvoke(shapeTool, 'GetShapes', shapesSeq)
  for (let i = 1; i <= shapesSeq.Length(); i++) addLabel(shapesSeq.Value(i))

  if (labels.length === 0) {
    const nb =
      shapeToolInvoke(shapeTool, 'NbShapes') ??
      (typeof shapeTool.NbShapes === 'function' ? shapeTool.NbShapes() : 0)
    const count = typeof nb === 'number' ? nb : 0
    for (let i = 1; i <= count; i++) {
      addLabel(shapeToolInvoke(shapeTool, 'GetShapeLabel', i))
    }
  }

  if (labels.length === 0) {
    const freeShapes = new oc.TDF_LabelSequence_1()
    shapeToolInvoke(shapeTool, 'GetFreeShapes', freeShapes)
    for (let r = 1; r <= freeShapes.Length(); r++) {
      const root = freeShapes.Value(r)
      const sub = new oc.TDF_LabelSequence_1()
      shapeToolInvoke(shapeTool, 'GetSubShapes', root, sub)
      for (let i = 1; i <= sub.Length(); i++) addLabel(sub.Value(i))
      const ChildIterator = oc.TDF_ChildIterator_2 ?? oc.TDF_ChildIterator_1 ?? oc.TDF_ChildIterator
      if (typeof ChildIterator === 'function') {
        const it = new ChildIterator(root, true)
        if (it && typeof it.More === 'function') {
          while (it.More()) {
            const child = it.Value()
            if (shapeToolInvoke(shapeTool, 'IsShape', child) === true) addLabel(child)
            it.Next()
          }
        }
      }
    }
  }

  return labels
}

/** Тесселяция всех форм по меткам ShapeTool (основной путь для сборок КОМПАС). */
function meshAllShapeLabelsInDocument(
  oc: any,
  shapeTool: any,
  colorTool: any,
  metizColor: any,
  colorType: number,
  partNames: PartInfo[],
  stats: XcafColorStats,
): number {
  const labels = collectAllShapeLabels(oc, shapeTool)
  console.log(`${LOG_PREFIX} XCAF: меток с формой (GetShapes/NbShapes): ${labels.length}`)
  let meshed = 0
  const t0 = performance.now()
  for (let i = 0; i < labels.length; i++) {
    const label = labels[i]
    const shape = getShapeForLabel(shapeTool, label, oc)
    if (!shape || shape.IsNull()) continue
    try {
      recordMeshedPart(
        oc,
        label,
        shape,
        shapeTool,
        colorTool,
        metizColor,
        colorType,
        partNames,
        stats,
      )
      meshed++
      if (meshed <= 5 || meshed % 200 === 0) {
        const name = getLabelNameFollowingRefs(oc, shapeTool, label) || getLabelName(oc, label)
        console.log(`${LOG_PREFIX} XCAF: затесселировано ${meshed}/${labels.length} — ${name || '(без имени)'}`)
      }
    } catch (e) {
      console.warn(`${LOG_PREFIX} XCAF: ошибка тесселяции метки ${i + 1}:`, e)
    }
  }
  console.log(
    `${LOG_PREFIX} XCAF: тесселяция меток ${meshed}/${labels.length} за ${((performance.now() - t0) / 1000).toFixed(2)} с`,
  )
  return meshed
}

function recordMeshedPart(
  oc: any,
  label: any,
  shape: any,
  shapeTool: any,
  colorTool: any,
  metizColor: any,
  colorType: number,
  partNames: PartInfo[],
  stats: XcafColorStats,
): void {
  tessellateShape(oc, shape)
  const name =
    getLabelNameFollowingRefs(oc, shapeTool, label) || getLabelName(oc, label) || '(без имени)'
  const isMetiz = isMetizByName(name)
  const resolved = resolveLabelColor(oc, colorTool, label, name, metizColor, stats)
  partNames.push({
    name,
    isMetiz,
    color: rgbToHex(...resolved.rgb),
    colorSource: resolved.colorSource,
  })
  try {
    applyResolvedColorToLabel(colorTool, label, colorType, resolved)
  } catch (e) {
    console.warn(`${LOG_PREFIX} XCAF: SetColor для «${name}»:`, e)
  }
}

/** Рекурсивный обход XCAF: сборки КОМПАС, ссылки, дочерние метки. */
function exploreXcafLabel(
  oc: any,
  label: any,
  shapeTool: any,
  colorTool: any,
  metizColor: any,
  colorType: number,
  partNames: PartInfo[],
  stats: XcafColorStats,
  depth: number,
  visited: Set<string>,
): void {
  if (depth > 96) return
  const labelKey = String(label?.Tag ?? label?.GetTag?.() ?? depth)
  if (visited.has(labelKey)) return
  visited.add(labelKey)

  const shape = getShapeForLabel(shapeTool, label, oc)
  let children = getChildLabels(oc, shapeTool, label)
  if (children.length === 0) {
    const referred = new oc.TDF_Label()
    if (shapeToolInvoke(shapeTool, 'GetReferredShape', label, referred) === true) {
      exploreXcafLabel(
        oc,
        referred,
        shapeTool,
        colorTool,
        metizColor,
        colorType,
        partNames,
        stats,
        depth + 1,
        visited,
      )
      return
    }
  }
  const isAssembly = children.length > 0 || shapeToolInvoke(shapeTool, 'IsAssembly', label) === true

  if (shape && !shape.IsNull() && !isAssembly) {
    recordMeshedPart(oc, label, shape, shapeTool, colorTool, metizColor, colorType, partNames, stats)
    return
  }

  for (const child of children) {
    exploreXcafLabel(
      oc,
      child,
      shapeTool,
      colorTool,
      metizColor,
      colorType,
      partNames,
      stats,
      depth + 1,
      visited,
    )
  }

  if (shape && !shape.IsNull() && isAssembly) {
    recordMeshedPart(oc, label, shape, shapeTool, colorTool, metizColor, colorType, partNames, stats)
  }
}

/** Обход всех меток под label через TDF_ChildIterator (allLevels=true) и меширование каждой с формой. */
function visitLabelsWithChildIterator(
  oc: any,
  label: any,
  shapeTool: any,
  colorTool: any,
  metizColor: any,
  colorType: number,
  partNames: PartInfo[],
  stats: XcafColorStats,
): void {
  const ChildIterator = oc.TDF_ChildIterator_2 ?? oc.TDF_ChildIterator_1 ?? oc.TDF_ChildIterator
  if (typeof ChildIterator !== 'function') return
  const it = new ChildIterator(label, true)
  if (!it || typeof it.More !== 'function') return
  while (it.More()) {
    const childLabel = it.Value()
    const shape = getShapeForLabel(shapeTool, childLabel, oc)
    if (shape && !shape.IsNull()) {
      recordMeshedPart(
        oc,
        childLabel,
        shape,
        shapeTool,
        colorTool,
        metizColor,
        colorType,
        partNames,
        stats,
      )
    }
    it.Next()
  }
}

/**
 * Загрузка STEP через XCAF: детали по меткам, цвета из файла, метизы — отдельным цветом.
 * При пустом обходе — экспорт CAF-документа целиком; при ошибке writer — откат на один shape.
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

  const metizColor =
    createPartColor(oc, 0.72, 0.72, 0.75, NOC_METIZ) ??
    createQuantityColor(oc, 'Quantity_NOC_GRAY80') ??
    createQuantityColor(oc, 'Quantity_NOC_WHITE')
  if (!metizColor) {
    console.warn(`${LOG_PREFIX} Quantity_Color недоступен — палитра в GLB может не примениться`)
  } else {
    console.log(`${LOG_PREFIX} Quantity_Color: RGB/NOC доступен`)
  }
  const colorType = oc.XCAFDoc_ColorGen

  updateXcafAssemblies(shapeTool)

  const freeShapes = new oc.TDF_LabelSequence_1()
  shapeToolInvoke(shapeTool, 'GetFreeShapes', freeShapes)
  const numRoots = freeShapes.Length()
  console.log(`${LOG_PREFIX} XCAF: GetFreeShapes готов, корневых меток: ${numRoots}`)
  const tVisit = performance.now()
  const partNames: PartInfo[] = []
  const colorStats: XcafColorStats = { fromFile: 0, palette: 0, metiz: 0 }

  meshAllShapeLabelsInDocument(
    oc,
    shapeTool,
    colorTool,
    metizColor,
    colorType,
    partNames,
    colorStats,
  )

  const visited = new Set<string>()
  if (partNames.length === 0) {
    console.log(`${LOG_PREFIX} XCAF: GetShapes пуст — обход дерева сборки...`)
  }
  for (let i = 1; i <= numRoots; i++) {
    if (partNames.length > 0) break
    exploreXcafLabel(
      oc,
      freeShapes.Value(i),
      shapeTool,
      colorTool,
      metizColor,
      colorType,
      partNames,
      colorStats,
      0,
      visited,
    )
    if (i <= 3 || i === numRoots) {
      console.log(`${LOG_PREFIX} XCAF: корень ${i}/${numRoots}, деталей с геометрией: ${partNames.length}`)
    }
  }
  if (partNames.length === 0 && numRoots > 0) {
    console.log(`${LOG_PREFIX} XCAF: explore не нашёл листьев — пробуем TDF_ChildIterator...`)
    for (let i = 1; i <= numRoots; i++) {
      visitLabelsWithChildIterator(
        oc,
        freeShapes.Value(i),
        shapeTool,
        colorTool,
        metizColor,
        colorType,
        partNames,
        colorStats,
      )
    }
    console.log(`${LOG_PREFIX} XCAF: после ChildIterator деталей с геометрией: ${partNames.length}`)
  }
  if (partNames.length === 0 && numRoots > 0) {
    const rootShape = getShapeForLabel(shapeTool, freeShapes.Value(1), oc)
    if (rootShape && !rootShape.IsNull()) {
      console.log(`${LOG_PREFIX} XCAF: тесселяция корневой формы (единый compound)`)
      tessellateShape(oc, rootShape)
      partNames.push({
        name: getLabelName(oc, freeShapes.Value(1)) || 'Сборка',
        isMetiz: false,
        color: '#b0b0b0',
        colorSource: 'palette',
      })
    }
  }
  if (partNames.length === 0) {
    throw new Error('XCAF: не удалось затесселировать ни одной формы')
  }
  console.log(
    `${LOG_PREFIX} XCAF: обход готов за ${((performance.now() - tVisit) / 1000).toFixed(2)} с, корней: ${numRoots}, деталей с геометрией: ${partNames.length}`,
  )
  if (partNames.length > 0) {
    console.log(
      `${LOG_PREFIX} Цвета XCAF: из файла ${colorStats.fromFile}, палитра ${colorStats.palette}, метизы ${colorStats.metiz}`
    )
    const logLimit = 40
    console.log(`${LOG_PREFIX} Найденные детали (первые ${Math.min(logLimit, partNames.length)}):`)
    partNames.slice(0, logLimit).forEach((p, idx) => {
      const src =
        p.colorSource === 'file' ? 'STEP' : p.colorSource === 'metiz' ? 'метиз' : 'палитра'
      console.log(`  ${idx + 1}. ${p.name} ${p.isMetiz ? '(метиз)' : ''} [${src}] — ${p.color}`)
    })
    if (partNames.length > logLimit) {
      console.log(`  … и ещё ${partNames.length - logLimit} деталей`)
    }
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

  tryUnlinkOcFs(oc, filename)
  tryUnlinkOcFs(oc, GLB_PATH)

  console.log(
    `${LOG_PREFIX} конвертация STEP/IGES→GLB всего: ${((performance.now() - tTotal) / 1000).toFixed(2)} с`
  )
  return url
}
