/**
 * Централизованный логгер для анализа выполнения приложения.
 * Формат как в nordfox: HH:mm:ss | LEVEL | source | message
 */

export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

export interface LogEntry {
  time: string
  level: LogLevel
  name: string
  message: string
}

const LEVEL_PAD = 8
const entries: LogEntry[] = []
let uiCallback: ((line: string) => void) | null = null

function formatTime(): string {
  const d = new Date()
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  const s = String(d.getSeconds()).padStart(2, '0')
  return `${h}:${m}:${s}`
}

function levelLabel(level: LogLevel): string {
  return level.toUpperCase().padEnd(LEVEL_PAD, ' ')
}

function formatLine(entry: LogEntry): string {
  return `${entry.time} | ${levelLabel(entry.level)} | ${entry.name} | ${entry.message}`
}

function emit(level: LogLevel, name: string, message: string): void {
  const entry: LogEntry = {
    time: formatTime(),
    level,
    name,
    message,
  }
  entries.push(entry)
  const line = formatLine(entry)
  if (level === 'error') console.error(line)
  else if (level === 'warn') console.warn(line)
  else console.log(line)
  uiCallback?.(line)
}

export const logger = {
  debug(name: string, message: string): void {
    emit('debug', name, message)
  },
  info(name: string, message: string): void {
    emit('info', name, message)
  },
  warn(name: string, message: string): void {
    emit('warn', name, message)
  },
  error(name: string, message: string, err?: unknown): void {
    let msg = message
    if (err !== undefined) {
      if (err instanceof Error) msg += ` ${err.message}${err.stack ? '\n' + err.stack : ''}`
      else msg += ` ${String(err)}`
    }
    emit('error', name, msg)
  },
  /** Подписка UI: при каждой новой записи вызывается callback с отформатированной строкой */
  setUiCallback(cb: ((line: string) => void) | null): void {
    uiCallback = cb
  },
  /** Все записи за сессию (для панели при открытии вкладки) */
  getEntries(): LogEntry[] {
    return [...entries]
  },
  /** Текст лога для сохранения в файл */
  getText(): string {
    return entries.map(formatLine).join('\n')
  },
  clear(): void {
    entries.length = 0
  },
}
