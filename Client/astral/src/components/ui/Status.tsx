import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../lib/api'
import { Button } from './Button'

export function Loading() {
  const { t } = useTranslation()
  return (
    <div className="space-y-3" aria-busy="true" aria-label={t('app.loading')}>
      <div className="h-6 w-1/3 rounded bg-hairline/70" />
      <div className="h-16 rounded bg-hairline/50" />
      <div className="h-16 rounded bg-hairline/50" />
    </div>
  )
}

// Access errors get the interface's own words; the API's text is meant for developers.
const CODE_MESSAGES: Record<string, string> = {
  NETWORK_ERROR: 'app.offline',
  UNAUTHENTICATED: 'access.signInAgain',
  FORBIDDEN: 'access.forbidden',
  OUT_OF_SCOPE: 'access.outOfScope',
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation()
  const api = error instanceof ApiError ? error : null
  const key = api && CODE_MESSAGES[api.code]
  const message = key ? t(key) : api ? api.message : String(error)
  // Retrying only helps when the server or the connection failed, not when access was refused.
  const retryable = !api || api.status === 0 || api.status >= 500
  return (
    <div role="alert" className="border-l-4 border-overdue bg-kerb p-4 text-sm">
      <p>{message}</p>
      {onRetry && retryable && (
        <Button className="mt-3" onClick={onRetry}>{t('app.retry')}</Button>
      )}
    </div>
  )
}

export function DemoBadge() {
  const { t } = useTranslation()
  return (
    <span
      title={t('app.demoDataHint')}
      className="inline-flex items-center rounded-[3px] border border-asphalt px-1.5 text-xs font-semibold"
    >
      {t('app.demoData')}
    </span>
  )
}

/** An empty screen says what to do next (DESIGN.md copy rules). */
export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="max-w-xl py-12">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="mt-2 text-road">{body}</p>
      {action && <div className="mt-6">{action}</div>}
    </div>
  )
}
