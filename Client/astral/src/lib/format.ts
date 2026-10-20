import i18n from '../i18n'

const locale = () => (i18n.language === 'ms' ? 'ms-MY' : 'en-MY')

export function formatNumber(value: number | null | undefined, digits = 0): string {
  return value === null || value === undefined
    ? '—'
    : new Intl.NumberFormat(locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value)
}

/** "in 5 h" / "3 h ago", for SLA countdowns and freshness labels. */
export function formatRelative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '—'
  const minutes = Math.round((new Date(iso).getTime() - now) / 60000)
  const rtf = new Intl.RelativeTimeFormat(locale(), { numeric: 'auto' })
  if (Math.abs(minutes) < 60) return rtf.format(minutes, 'minute')
  if (Math.abs(minutes) < 60 * 48) return rtf.format(Math.round(minutes / 60), 'hour')
  return rtf.format(Math.round(minutes / 1440), 'day')
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Intl.DateTimeFormat(locale(), { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kuala_Lumpur' }).format(new Date(iso))
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Intl.DateTimeFormat(locale(), { dateStyle: 'medium', timeZone: 'Asia/Kuala_Lumpur' }).format(new Date(iso))
}

export function formatMonth(yyyyMm: string): string {
  const [y, m] = yyyyMm.split('-').map(Number)
  return new Intl.DateTimeFormat(locale(), { month: 'short' }).format(new Date(y, m - 1, 1))
}
