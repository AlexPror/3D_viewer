/** Классификация деталей сборки по имени (как группы в дереве КОМПАС). */

export type PartCategoryId =
  | 'embed'
  | 'fastener'
  | 'frame'
  | 'plate'
  | 'pipe'
  | 'equipment'
  | 'other'

export const PART_CATEGORY_ORDER: PartCategoryId[] = [
  'frame',
  'plate',
  'embed',
  'fastener',
  'pipe',
  'equipment',
  'other',
]

export const PART_CATEGORY_LABELS: Record<PartCategoryId, string> = {
  frame: 'Каркас и балки',
  plate: 'Листы и пластины',
  embed: 'Закладные',
  fastener: 'Метизы',
  pipe: 'Трубы и арматура',
  equipment: 'Оборудование',
  other: 'Прочее',
}

const CATEGORY_RULES: { id: PartCategoryId; re: RegExp }[] = [
  {
    id: 'embed',
    re: /заклад|закл\.|embedded|insert|анкер|закладн|вставк/i,
  },
  {
    id: 'fastener',
    re: /болт|гайк|шайб|винт|метиз|шпильк|заклеп|fastener|screw|nut|bolt|stud|washer|rivet/i,
  },
  { id: 'frame', re: /балк|колонн|ригел|ферм|каркас|beam|column|frame|truss|profile/i },
  { id: 'plate', re: /лист|пластин|plate|sheet|panel|flange|фланец/i },
  { id: 'pipe', re: /труб|pipe|tube|арматур|клапан|valve|fitting/i },
  {
    id: 'equipment',
    re: /насос|vent|клапан|оборуд|pump|motor|двигат|агрегат|unit/i,
  },
]

export function normalizePartLabel(raw: string): string {
  const s = String(raw || '').trim()
  if (!s) return ''
  const noQty = s.replace(/\s*\(\d+\)\s*$/g, '')
  const noTailNum = noQty.replace(/([._-])\d{1,4}$/g, '')
  return noTailNum.replace(/\s{2,}/g, ' ').trim()
}

export function inferPartCategory(label: string): PartCategoryId {
  const l = normalizePartLabel(label).toLowerCase()
  if (!l) return 'other'
  for (const rule of CATEGORY_RULES) {
    if (rule.re.test(l)) return rule.id
  }
  return 'other'
}

/** Ключ группы одинаковых деталей (один тип — несколько экземпляров в сборке). */
export function partGroupKey(label: string): string {
  return normalizePartLabel(label).toLowerCase()
}

export interface PartMeshBucket {
  label: string
  categoryId: PartCategoryId
  ids: string[]
  visibleCount: number
}
