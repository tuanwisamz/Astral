import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { buttonClass } from '../../components/ui/Button'
import type { FormError } from '../../lib/clerkErrors'

export function AuthHeading({ title, body }: { title: string; body?: ReactNode }) {
  return (
    <div className="mb-8">
      <h1 className="text-2xl font-semibold">{title}</h1>
      {body && <p className="mt-2 text-road">{body}</p>}
    </div>
  )
}

/** Errors that belong to no single field sit above the form. */
export function FormAlert({ error }: { error: FormError | null }) {
  if (!error || error.field !== 'form') return null
  return <p role="alert" className="mb-6 border-l-4 border-overdue pl-3 text-sm">{error.message}</p>
}

export const fieldError = (error: FormError | null, field: FormError['field']) =>
  error?.field === field ? error.message : undefined

export function OrDivider() {
  const { t } = useTranslation()
  return (
    <div className="my-6 flex items-center gap-3 text-sm text-road">
      <span className="h-px flex-1 bg-hairline" />
      {t('auth.or')}
      <span className="h-px flex-1 bg-hairline" />
    </div>
  )
}

/** Shown instead of a form when this copy of the app has no Clerk key. */
export function AuthNotConnected() {
  const { t } = useTranslation()
  return (
    <>
      <AuthHeading title={t('auth.notConnectedTitle')} body={t('auth.notConnectedBody')} />
      <Link to="/map" className={buttonClass('secondary')}>{t('auth.openMap')}</Link>
    </>
  )
}

// Google's standard "G" mark, in its own colours as the sign-in branding guidelines require.
function GoogleMark() {
  return (
    <svg aria-hidden="true" width="18" height="18" viewBox="0 0 48 48" className="shrink-0">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  )
}

export function GoogleButton({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) {
  const { t } = useTranslation()
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={buttonClass('secondary', 'w-full gap-3')}>
      <GoogleMark />
      {t('auth.google')}
    </button>
  )
}
