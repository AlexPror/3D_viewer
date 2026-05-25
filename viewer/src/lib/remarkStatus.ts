export type RemarkStatus = 'open' | 'answered' | 'accepted' | 'rejected'

export type RemarkStatusFilter = RemarkStatus | 'all'

export const REMARK_STATUS_OPTIONS: { value: RemarkStatus; label: string }[] = [
  { value: 'open', label: 'Открыто' },
  { value: 'answered', label: 'Отвечено' },
  { value: 'accepted', label: 'Принято' },
  { value: 'rejected', label: 'Отклонено' },
]

export function remarkStatusLabel(status: RemarkStatus): string {
  return REMARK_STATUS_OPTIONS.find((o) => o.value === status)?.label ?? status
}

export function normalizeRemarkStatus(raw?: string | null): RemarkStatus {
  if (raw === 'answered' || raw === 'accepted' || raw === 'rejected') return raw
  return 'open'
}

export function remarkStatusCssClass(status: RemarkStatus): string {
  return `remark-status--${status}`
}
