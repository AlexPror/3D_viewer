<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { logger } from './lib/logger'
import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'
import type { ViewMode, MeasureSnapMode, MeasureType } from './components/ViewerToolbar.vue'
import Viewer3D from './components/Viewer3D.vue'
import ViewerToolbar from './components/ViewerToolbar.vue'
import PdfViewer from './components/PdfViewer.vue'
import LogPanel from './components/LogPanel.vue'
import ScreenshotEditorModal from './components/ScreenshotEditorModal.vue'

const viewMode = ref<ViewMode>('split')
const viewerRef = ref<InstanceType<typeof Viewer3D> | null>(null)
const pdfViewerRef = ref<InstanceType<typeof PdfViewer> | null>(null)
const pdfFile = ref<{ url: string; name: string } | null>(null)
interface ReportScreenshotItem {
  id: string
  type: '2d' | '3d'
  dataUrl: string
  /** для 2d: имя файла PDF */
  pdfFileName?: string
  /** для 2d: номер страницы скриншота */
  pageNumber?: number
}
const screenshotImageUrl = ref<string | null>(null)
const screenshotSuggestedFileName = ref<string | null>(null)
const showScreenshotModal = ref(false)
const screenshotSourceType = ref<'2d' | '3d'>('2d')
const editingScreenshotId = ref<string | null>(null)
const reportScreenshots = ref<ReportScreenshotItem[]>([])
const reportProjectName = ref('')
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

const MODEL_EXTENSIONS = ['stl', 'step', 'stp', 'igs', 'iges', 'glb', 'gltf']

let pdfInput: HTMLInputElement | null = null

function onDragOver(e: DragEvent) {
  if (!e.dataTransfer?.types.includes('Files')) return
  e.preventDefault()
  e.dataTransfer.dropEffect = 'copy'
  isDraggingFile.value = true
}

function onDragLeave() {
  isDraggingFile.value = false
}

function onDrop(e: DragEvent) {
  isDraggingFile.value = false
  if (!e.dataTransfer?.types.includes('Files')) return
  e.preventDefault()
  const file = e.dataTransfer.files?.[0]
  if (!file) return
  const ext = (file.name.split('.').pop() || '').toLowerCase()
  if (ext === 'pdf') {
    logger.info('App', `PDF открыт: ${file.name}`)
    if (pdfFile.value?.url) URL.revokeObjectURL(pdfFile.value.url)
    pdfFile.value = { url: URL.createObjectURL(file), name: file.name }
    return
  }
  if (MODEL_EXTENSIONS.includes(ext)) {
    logger.info('App', `3D файл сброшен: ${file.name}`)
    if (viewMode.value === '2d' || viewMode.value === 'log') viewMode.value = 'split'
    setTimeout(() => viewerRef.value?.loadModelFile?.(file), 0)
    return
  }
  alert('Поддерживаются PDF и 3D (STL, STEP, IGES, GLB)')
}

function onOpenPdf() {
  if (!pdfInput) {
    pdfInput = document.createElement('input')
    pdfInput.type = 'file'
    pdfInput.accept = '.pdf'
    pdfInput.onchange = () => {
      const file = pdfInput?.files?.[0]
      if (file) {
        logger.info('App', `PDF выбран: ${file.name}`)
        if (pdfFile.value?.url) URL.revokeObjectURL(pdfFile.value.url)
        pdfFile.value = { url: URL.createObjectURL(file), name: file.name }
      }
      if (pdfInput) pdfInput.value = ''
    }
  }
  pdfInput.click()
}

function onViewModeChange(mode: ViewMode) {
  viewMode.value = mode
  logger.info('App', `Режим вида: ${mode}`)
}

function onOpenFile() {
  logger.info('App', 'Открыть 3D модель (диалог)')
  viewerRef.value?.openFileDialog()
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
      if ('triangle' in report && report.triangle) {
        doc.text(
          `${MEASURE_LABELS.length}: ${report.lengths[0].toFixed(2)} ${MEASURE_LABELS.mm}  |  ${report.lengths[1].toFixed(2)} ${MEASURE_LABELS.mm}  |  ${report.lengths[2].toFixed(2)} ${MEASURE_LABELS.mm}`,
          margin,
          y
        )
      } else {
        doc.text(`${MEASURE_LABELS.length}: ${report.length.toFixed(2)} ${MEASURE_LABELS.mm}`, margin, y)
        y += lineH
        doc.text(
          `ΔX: ${report.dx.toFixed(2)} ${MEASURE_LABELS.mm}  ΔY: ${report.dy.toFixed(2)} ${MEASURE_LABELS.mm}  ΔZ: ${report.dz.toFixed(2)} ${MEASURE_LABELS.mm}`,
          margin,
          y
        )
      }
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

async function onScreenshotTab() {
  logger.info('App', `Скриншот вкладки: getDisplayMedia=${!!navigator.mediaDevices?.getDisplayMedia}`)
  if (!navigator.mediaDevices?.getDisplayMedia) {
    logger.warn('App', 'Скриншот вкладки: API недоступен (нужен HTTPS и современный браузер)')
    alert('Захват вкладки недоступен. Используйте современный браузер и HTTPS.')
    return
  }
  try {
    const stream = await navigator.mediaDevices.getDisplayMedia({
      video: { displaySurface: 'browser' },
      audio: false,
    })
    logger.info('App', 'Скриншот вкладки: поток получен')
    const video = document.createElement('video')
    video.muted = true
    video.playsInline = true
    video.srcObject = stream
    const CAPTURE_WAIT_MS = 5000
    const pollStepMs = 100
    const waitForFrame = async (): Promise<{ w: number; h: number }> => {
      await video.play()
      const deadline = Date.now() + CAPTURE_WAIT_MS
      while (video.videoWidth === 0 || video.videoHeight === 0) {
        if (Date.now() >= deadline) throw new Error('timeout')
        await new Promise((r) => setTimeout(r, pollStepMs))
      }
      await new Promise((r) => requestAnimationFrame(r))
      return { w: video.videoWidth, h: video.videoHeight }
    }
    let w: number
    let h: number
    try {
      const size = await Promise.race([
        waitForFrame(),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('timeout')), CAPTURE_WAIT_MS + 500)
        ),
      ])
      w = size.w
      h = size.h
    } catch (err) {
      stream.getTracks().forEach((t) => t.stop())
      logger.warn('App', 'Скриншот вкладки: не удалось получить кадр за 5 с')
      alert('Не удалось получить кадр. Попробуйте снова или выберите вкладку явно.')
      return
    }
    logger.info('App', `Скриншот вкладки: видео размер ${w}×${h}`)
    const dpr = window.devicePixelRatio || 1
    const iframeEl = document.querySelector('.pdf-iframe') as HTMLElement | null
    let drawW = w
    let drawH = h
    let sx = 0
    let sy = 0
    let sw = w
    let sh = h
    if (iframeEl) {
      const rect = iframeEl.getBoundingClientRect()
      sx = Math.round(rect.left * dpr)
      sy = Math.round(rect.top * dpr)
      sw = Math.round(rect.width * dpr)
      sh = Math.round(rect.height * dpr)
      sx = Math.max(0, Math.min(sx, w - 1))
      sy = Math.max(0, Math.min(sy, h - 1))
      sw = Math.min(sw, w - sx)
      sh = Math.min(sh, h - sy)
      if (sw > 0 && sh > 0) {
        drawW = sw
        drawH = sh
        logger.info('App', `Скриншот вкладки: обрезка по iframe ${drawW}×${drawH}`)
      } else {
        sx = 0
        sy = 0
        sw = w
        sh = h
      }
    }
    const canvas = document.createElement('canvas')
    canvas.width = drawW
    canvas.height = drawH
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      logger.warn('App', 'Скриншот вкладки: не удалось получить 2D контекст canvas')
      stream.getTracks().forEach((t) => t.stop())
      return
    }
    ctx.drawImage(video, sx, sy, sw, sh, 0, 0, drawW, drawH)
    const url = canvas.toDataURL('image/png')
    stream.getTracks().forEach((t) => t.stop())
    screenshotSourceType.value = '2d'
    savedPdfPageForNextScreenshot.value = pdfViewerRef.value?.getScreenshotPage?.() ?? 1
    screenshotImageUrl.value = url
    screenshotSuggestedFileName.value = `вкладка-${new Date().toISOString().slice(0, 10)}`
    showScreenshotModal.value = true
    logger.info('App', `Скриншот вида вкладки получен, dataURL длина=${url.length}`)
  } catch (e) {
    if (e instanceof Error && e.name === 'NotAllowedError') {
      logger.info('App', 'Скриншот вкладки: пользователь отменил выбор источника')
    } else {
      logger.error('App', 'Скриншот вкладки: ошибка захвата', e)
      alert('Не удалось захватить вид. Убедитесь, что используется HTTPS.')
    }
  }
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
      }
      reportScreenshots.value.push(item)
      logger.info('App', `Редактор скриншота: добавлен ${type === '2d' ? '2D' : '3D'} скриншот в отчёт (всего ${reportScreenshots.value.length})`)
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
  editingScreenshotId.value = item.id
  screenshotSourceType.value = item.type
  screenshotImageUrl.value = item.dataUrl
  screenshotSuggestedFileName.value = item.type === '2d' ? '2d-скриншот' : '3d-скриншот'
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

function onScreenshotDragStart(e: DragEvent, index: number) {
  if (!e.dataTransfer) return
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', String(index))
  e.dataTransfer.setData('application/x-screenshot-index', String(index))
}

function onScreenshotDragOver(e: DragEvent) {
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
}

function onScreenshotDrop(e: DragEvent, toIndex: number) {
  e.preventDefault()
  if (!e.dataTransfer) return
  const fromIndex = Number(e.dataTransfer.getData('text/plain'))
  if (Number.isNaN(fromIndex) || fromIndex === toIndex) return
  const arr = [...reportScreenshots.value]
  if (fromIndex < 0 || fromIndex >= arr.length || toIndex < 0 || toIndex >= arr.length) return
  const [item] = arr.splice(fromIndex, 1)
  arr.splice(toIndex, 0, item)
  reportScreenshots.value = arr
  logger.info('App', `Скриншот перемещён с ${fromIndex + 1} на ${toIndex + 1}`)
}

async function fillProjectNameFromFirstSheet() {
  await refreshFirstSheetData()
}

function sanitizeFileName(s: string): string {
  return s.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').trim() || 'проект'
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
  window.addEventListener('dragover', onDragOver)
  window.addEventListener('drop', onDrop)
  window.addEventListener('dragleave', onDragLeave)
})

onUnmounted(() => {
  window.removeEventListener('dragover', onDragOver)
  window.removeEventListener('drop', onDrop)
  window.removeEventListener('dragleave', onDragLeave)
})
</script>

<template>
  <div class="app" :class="{ 'is-dragging-file': isDraggingFile }">
    <div v-if="isDraggingFile" class="drop-overlay">Отпустите файл (PDF или 3D)</div>
    <ViewerToolbar
      :view-mode="viewMode"
      :section-mode="sectionMode"
      :section-active="sectionActive"
      :section-offset="sectionOffset"
      :measure-mode="measureMode"
      :measure-snap-mode="measureSnapMode"
      :measure-type="measureType"
      @update:view-mode="onViewModeChange"
      @open-pdf="onOpenPdf"
      @open-file="onOpenFile"
      @reset-view="onResetView"
      @screenshot-2d="onScreenshotTab"
      @screenshot-3d="onScreenshot3D"
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
      @export-report="onExportReport"
    />
    <div class="report-screenshots-panel">
      <div class="report-screenshots-header">
        <span class="report-screenshots-title">Скриншоты для отчёта</span>
        <span class="report-screenshots-count">({{ reportScreenshots.length }})</span>
      </div>
      <div class="report-params">
        <label class="report-params-label">Название проекта:</label>
        <input v-model="reportProjectName" type="text" class="report-params-input" placeholder="10-23-КП-Р-НВФ1.1" />
        <button type="button" class="report-params-btn" title="Взять с первого листа PDF" @click="fillProjectNameFromFirstSheet">С 1-го листа</button>
        <label class="report-params-label">Номер листа:</label>
        <input v-model="reportSheetNumber" type="text" class="report-params-input" placeholder="1" />
        <label class="report-params-label">Автор замечаний:</label>
        <input v-model="reportAuthor" type="text" class="report-params-input" placeholder="Фамилия Имя" />
      </div>
      <div v-if="reportScreenshots.length === 0" class="report-screenshots-empty">
        Делайте скриншоты кнопками «Скриншот 2D» / «Скриншот 3D» — после закрытия редактора они появятся здесь и попадут в отчёт.
      </div>
      <div v-else class="report-screenshots-list">
        <div
          v-for="(item, index) in reportScreenshots"
          :key="item.id"
          class="report-screenshot-card"
          draggable="true"
          @dragstart="onScreenshotDragStart($event, index)"
          @dragover="onScreenshotDragOver($event)"
          @drop="onScreenshotDrop($event, index)"
        >
          <img :src="item.dataUrl" :alt="item.type" class="report-screenshot-thumb" draggable="false" />
          <span class="report-screenshot-type">{{ item.type === '2d' ? '2D' : '3D' }}</span>
          <div class="report-screenshot-actions">
            <button type="button" class="report-screenshot-btn" title="Выше в отчёте" :disabled="index === 0" @click="moveScreenshotUp(index)">↑</button>
            <button type="button" class="report-screenshot-btn" title="Ниже в отчёте" :disabled="index === reportScreenshots.length - 1" @click="moveScreenshotDown(index)">↓</button>
            <button type="button" class="report-screenshot-btn" title="Редактировать" @click="openEditorForScreenshot(item)">✎</button>
            <button type="button" class="report-screenshot-btn report-screenshot-btn-remove" title="Удалить из отчёта" @click="removeScreenshotFromReport(item)">×</button>
          </div>
        </div>
      </div>
    </div>
    <div class="content" :class="'mode-' + viewMode">
      <div v-show="showPdfPanel()" class="panel pdf-panel">
        <PdfViewer
          v-if="pdfFile"
          ref="pdfViewerRef"
          :pdf-url="pdfFile.url"
          :pdf-name="pdfFile.name"
        />
        <div v-else class="panel-placeholder">Выберите PDF (чертежи, спецификация)</div>
      </div>
      <div v-show="show3dPanel()" class="panel viewer-panel">
        <Viewer3D
        ref="viewerRef"
        @section-active="onSectionActive"
        @section-inactive="onSectionInactive"
        @section-offset-changed="onSectionOffsetChanged"
      />
      </div>
      <div v-show="showLogPanel()" class="panel log-panel-wrap">
        <LogPanel />
      </div>
    </div>
    <ScreenshotEditorModal
      v-if="showScreenshotModal && screenshotImageUrl"
      :image-url="screenshotImageUrl!"
      :suggested-file-name="screenshotSuggestedFileName"
      @close="onScreenshotEditorClose"
      @final-image="onScreenshotEditorFinalImage"
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
.report-screenshots-panel {
  flex-shrink: 0;
  background: #1e2433;
  border-bottom: 1px solid #3a4a6a;
  padding: 0.4rem 0.6rem;
  max-height: 200px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.report-params {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.6rem;
  margin-bottom: 0.35rem;
}
.report-params-label {
  font-size: 0.8rem;
  color: #8a9bb5;
  white-space: nowrap;
}
.report-params-input {
  width: 10rem;
  max-width: 140px;
  padding: 0.25rem 0.4rem;
  font-size: 0.85rem;
  background: #2d3a52;
  border: 1px solid #4a5f7a;
  border-radius: 4px;
  color: #e0e8f0;
}
.report-params-input::placeholder {
  color: #6a7a8a;
}
.report-params-btn {
  padding: 0.25rem 0.5rem;
  font-size: 0.8rem;
  background: #3d4a62;
  color: #e0e8f0;
  border: 1px solid #4a5f7a;
  border-radius: 4px;
  cursor: pointer;
}
.report-params-btn:hover {
  background: #4a6fc7;
  border-color: #5a7fd7;
}
.report-screenshots-header {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin-bottom: 0.35rem;
  font-size: 0.85rem;
  color: #8a9bb5;
}
.report-screenshots-title {
  font-weight: 600;
  color: #e0e8f0;
}
.report-screenshots-count {
  color: #8a9bb5;
}
.report-screenshots-empty {
  font-size: 0.8rem;
  color: #6a7a8a;
  padding: 0.25rem 0;
}
.report-screenshots-list {
  display: flex;
  gap: 0.5rem;
  overflow-x: auto;
  padding: 0.2rem 0;
  align-items: flex-end;
}
.report-screenshot-card {
  flex-shrink: 0;
  width: 80px;
  position: relative;
  background: #252525;
  border: 1px solid #3a4a6a;
  border-radius: 6px;
  overflow: hidden;
  cursor: grab;
  user-select: none;
}
.report-screenshot-card:active {
  cursor: grabbing;
}
.report-screenshot-thumb {
  display: block;
  width: 80px;
  height: 60px;
  object-fit: contain;
  background: #1a1a1a;
}
.report-screenshot-type {
  position: absolute;
  top: 2px;
  left: 4px;
  font-size: 0.65rem;
  color: #fff;
  background: rgba(0, 0, 0, 0.6);
  padding: 1px 4px;
  border-radius: 3px;
}
.report-screenshot-actions {
  position: absolute;
  bottom: 2px;
  right: 2px;
  display: flex;
  gap: 2px;
}
.report-screenshot-btn {
  width: 22px;
  height: 22px;
  padding: 0;
  font-size: 0.9rem;
  line-height: 1;
  border: none;
  border-radius: 4px;
  background: rgba(74, 111, 199, 0.9);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.report-screenshot-btn:hover:not(:disabled) {
  background: #4a6fc7;
}
.report-screenshot-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.report-screenshot-btn-remove {
  background: rgba(180, 60, 60, 0.9);
}
.report-screenshot-btn-remove:hover {
  background: #b43c3c;
}
.content {
  flex: 1;
  min-height: 0;
  display: flex;
}
.content.mode-split .panel {
  flex: 1;
  min-width: 0;
}
.content.mode-split .pdf-panel {
  flex: 0 0 50%;
}
.content.mode-split .viewer-panel {
  flex: 0 0 50%;
}
.content.mode-2d .pdf-panel {
  flex: 1;
  min-width: 0;
}
.content.mode-3d .viewer-panel {
  flex: 1 1 100%;
  width: 100%;
  min-width: 0;
  height: 100%;
}
.panel.pdf-panel {
  background: #1a2228;
}
.content.mode-log .log-panel-wrap {
  flex: 1;
  min-width: 0;
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
.viewer-panel {
  position: relative;
}
</style>
