import { useQuery } from '@tanstack/react-query'
import { Suspense, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, Outlet, useLocation } from 'react-router'

import { LanguageToggle } from '../components/LanguageToggle'
import { Onboarding } from '../components/Onboarding'
import { buttonClass } from '../components/ui/Button'
import { RoleBadge } from '../components/ui/RoleBadge'
import { DemoBadge, Loading } from '../components/ui/Status'
import { formatRelative } from '../lib/format'
import type { District, MetaConfig, StateInfo } from '../lib/types'
import { AUTH_CONFIGURED, isStaff, useApi, useAuthState, type AuthState } from './auth'
import { useScope } from './scope'

type NavItem = { to: string; key: string; end?: boolean }

// Workflow order: Detect → Predict → Prioritise → Act (spec §9.2 Conceptual model).
function navFor(auth: AuthState): NavItem[] {
  if (!isStaff(auth.role)) {
    return [
      { to: '/map', key: 'nav.map' },
      { to: '/report', key: 'nav.report' },
      ...(auth.isSignedIn ? [{ to: '/my-reports', key: 'nav.myReports' }, { to: '/settings', key: 'nav.settings' }] : []),
    ]
  }
  return [
    { to: '/', key: 'nav.dashboard', end: true },
    { to: '/map', key: 'nav.map' },
    { to: '/priority', key: 'nav.priority' },
    { to: '/zones', key: 'nav.zones' },
    { to: '/analysis', key: 'nav.analysis' },
    { to: '/assistant', key: 'nav.assistant' },
    ...(auth.role === 'admin' || auth.role === 'dev' ? [{ to: '/admin', key: 'nav.admin' }] : []),
    { to: '/settings', key: 'nav.settings' },
  ]
}

/** State › District, following the agency hierarchy (spec §9.2 Mapping). */
function ScopeBreadcrumb() {
  const { t } = useTranslation()
  const api = useApi()
  const [scope, setScope] = useScope()
  const states = useQuery({ queryKey: ['states'], queryFn: () => api<StateInfo[]>('/meta/states') })
  const districts = useQuery({
    queryKey: ['districts', scope.state],
    queryFn: () => api<District[]>('/meta/districts', { params: { state: scope.state } }),
    enabled: Boolean(scope.state),
  })
  const select =
    'min-h-11 max-w-48 truncate rounded border border-transparent bg-transparent px-2 font-medium hover:border-hairline'
  return (
    <nav aria-label={t('scope.label')}
      className="order-last flex w-full min-w-0 items-center gap-1 md:order-none md:w-auto">
      <label className="sr-only" htmlFor="scope-state">{t('scope.state')}</label>
      <select id="scope-state" className={select} value={scope.state}
        onChange={(e) => setScope({ state: e.target.value, district: '' })}>
        <option value="">{t('scope.all')}</option>
        {states.data?.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
      </select>
      {scope.state && (
        <>
          <span aria-hidden="true" className="text-road">›</span>
          <label className="sr-only" htmlFor="scope-district">{t('scope.district')}</label>
          <select id="scope-district" className={select} value={scope.district}
            onChange={(e) => setScope({ ...scope, district: e.target.value })}>
            <option value="">{t('scope.allDistricts')}</option>
            {districts.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </>
      )}
    </nav>
  )
}

function Freshness() {
  const { t } = useTranslation()
  const api = useApi()
  const config = useQuery({ queryKey: ['config'], queryFn: () => api<MetaConfig>('/meta/config') })
  if (!config.data) return null
  return (
    <div className="hidden items-center gap-3 text-sm text-road md:flex">
      {config.data.synthetic_data_present && <DemoBadge />}
      <span>{t('app.updated', { when: formatRelative(config.data.data_freshness.incidents) })}</span>
    </div>
  )
}

function AccountMenu() {
  const { t } = useTranslation()
  const auth = useAuthState()
  if (!AUTH_CONFIGURED) {
    return (
      <div className="flex items-center gap-3">
        <RoleBadge role={auth.role} />
        <span className="hidden text-sm text-road lg:inline">{t('app.devMode')}</span>
      </div>
    )
  }
  if (!auth.isLoaded) return null
  if (!auth.isSignedIn) {
    return <Link to="/sign-in" className={buttonClass('secondary')}>{t('app.signIn')}</Link>
  }
  return (
    <div className="flex items-center gap-3">
      <RoleBadge role={auth.role} />
      <Link to="/settings" className="hidden max-w-48 truncate text-sm text-road underline-offset-4 hover:underline sm:inline">{auth.email}</Link>
      <button type="button" onClick={() => void auth.signOut()} className={buttonClass('quiet', 'px-2')}>
        {t('app.signOut')}
      </button>
    </div>
  )
}

export default function Layout() {
  const { t } = useTranslation()
  const auth = useAuthState()
  const location = useLocation()
  // The menu belongs to the page it was opened on, so navigating closes it without an effect.
  const [openOn, setOpenOn] = useState<string | null>(null)
  const navOpen = openOn === location.pathname
  const setNavOpen = (open: boolean) => setOpenOn(open ? location.pathname : null)
  const staff = isStaff(auth.role)

  const link = ({ isActive }: { isActive: boolean }) =>
    `relative flex min-h-11 items-center rounded-r px-5 text-base ${
      isActive
        ? 'font-semibold text-kerb before:absolute before:inset-y-1.5 before:left-0 before:w-1 before:bg-marking'
        : 'text-kerb/80 hover:bg-white/5 hover:text-kerb'
    }`

  return (
    <div className="flex h-full">
      <nav id="main-nav" aria-label={t('nav.main')}
        className={`${navOpen ? 'fixed inset-y-0 left-0 z-[1500] flex' : 'hidden'} w-56 shrink-0 flex-col bg-asphalt py-5 pr-3 md:static md:flex`}>
        <Link to="/" className="mb-8 px-5 font-condensed text-xl leading-tight font-semibold text-kerb">
          {t('app.name')}
        </Link>
        <div className="space-y-0.5">
          {navFor(auth).map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={link}>{t(item.key)}</NavLink>
          ))}
        </div>
      </nav>
      {navOpen && (
        <button type="button" aria-label={t('app.closeMenu')} onClick={() => setNavOpen(false)}
          className="fixed inset-0 z-[1400] bg-asphalt/40 md:hidden" />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex min-h-16 flex-wrap items-center gap-x-3 gap-y-1 border-b border-hairline bg-kerb px-4 py-2">
          <button type="button" className={buttonClass('secondary', 'px-3 md:hidden')}
            aria-expanded={navOpen} aria-controls="main-nav" onClick={() => setNavOpen(true)}>
            {t('app.menu')}
          </button>
          {staff && <ScopeBreadcrumb />}
          <div className="ml-auto flex items-center gap-4">
            <Freshness />
            <LanguageToggle />
            {!staff && location.pathname !== '/report' && (
              <Link to="/report" className={buttonClass('primary', 'hidden sm:inline-flex')}>{t('nav.report')}</Link>
            )}
            <AccountMenu />
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-auto">
          <Suspense fallback={<div className="p-6"><Loading /></div>}>
            <Outlet />
          </Suspense>
        </main>
        {staff && <Onboarding />}
      </div>
    </div>
  )
}
