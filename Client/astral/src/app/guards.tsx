import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useLocation, useSearchParams } from 'react-router'

import { buttonClass } from '../components/ui/Button'
import { EmptyState, Loading } from '../components/ui/Status'
import { isStaff, landingFor, useAuthState, type Role } from './auth'

/** Only same-site paths are accepted as a return target, so ?redirect= can't send people elsewhere. */
export function safeRedirect(value: string | null): string | null {
  return value && value.startsWith('/') && !value.startsWith('//') ? value : null
}

function NotConfigured() {
  const { t } = useTranslation()
  return <div className="p-6"><EmptyState title={t('access.notConfiguredTitle')} body={t('access.notConfiguredBody')} /></div>
}

/** Signed-out visitors go to sign in and come back to this page afterwards (FR-ACC-04). */
export function RequireSignIn({ children }: { children: ReactNode }) {
  const auth = useAuthState()
  const location = useLocation()
  if (auth.role === 'dev') return children
  if (!auth.configured) return <NotConfigured />
  if (!auth.isLoaded) return <div className="p-6"><Loading /></div>
  if (!auth.isSignedIn) {
    const back = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/sign-in?redirect=${back}`} replace />
  }
  return children
}

export function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { t } = useTranslation()
  const auth = useAuthState()
  const allowed = auth.role === 'dev' || (roles as string[]).includes(auth.role)
  return (
    <RequireSignIn>
      {allowed ? (
        children
      ) : (
        <div className="p-6">
          <EmptyState
            title={t('access.deniedTitle')}
            body={t(roles.includes('officer') ? 'access.deniedOfficer' : 'access.deniedAdmin')}
            action={<Link to={landingFor(auth.role)} className={buttonClass('secondary')}>{t('access.goHome')}</Link>}
          />
        </div>
      )}
    </RequireSignIn>
  )
}

/** "/" is the Dashboard for staff, the public map for other signed-in people, and the landing page otherwise. */
export function Home({ dashboard }: { dashboard: ReactNode }) {
  const auth = useAuthState()
  if (!auth.isLoaded) return <div className="p-6"><Loading /></div>
  if (isStaff(auth.role) && (auth.isSignedIn || auth.role === 'dev')) return dashboard
  return <Navigate to={auth.isSignedIn ? '/map' : '/welcome'} replace />
}

/** Signed-in people opening an account page go where they were heading, or to their landing page. */
export function GuestOnly({ children }: { children: ReactNode }) {
  const auth = useAuthState()
  const [params] = useSearchParams()
  if (auth.configured && auth.isLoaded && auth.isSignedIn) {
    return <Navigate to={safeRedirect(params.get('redirect')) ?? landingFor(auth.role)} replace />
  }
  return children
}
