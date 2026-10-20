import { useTranslation } from 'react-i18next'
import { Link, Outlet } from 'react-router'

import { GuestOnly } from '../../app/guards'
import { RoutePlate } from '../../components/ui/RoutePlate'

const CENTRE_LINE = 'repeating-linear-gradient(var(--dir), var(--color-marking) 0 44px, transparent 44px 80px)'

/** Form on the left; on the right, the product's subject in its own material (DESIGN.md). */
export default function AuthLayout() {
  const { t } = useTranslation()
  return (
    <GuestOnly>
      <div className="min-h-full bg-kerb lg:grid lg:grid-cols-2">
        <div className="relative h-12 bg-asphalt lg:hidden" aria-hidden="true">
          <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2"
            style={{ background: CENTRE_LINE.replace('var(--dir)', 'to right') }} />
        </div>

        <main className="px-6 py-10 sm:px-12 lg:py-14">
          <Link to="/" className="text-lg font-semibold">{t('app.name')}</Link>
          <div className="mt-12 w-full max-w-sm sm:mt-20">
            <Outlet />
          </div>
        </main>

        <aside className="relative hidden overflow-hidden bg-asphalt text-kerb lg:flex lg:flex-col lg:justify-end lg:p-14">
          <div className="absolute inset-y-0 left-[82%] w-1.5" aria-hidden="true"
            style={{ background: CENTRE_LINE.replace('var(--dir)', 'to bottom') }} />
          <div className="relative max-w-sm">
            <div className="flex gap-2">
              <RoutePlate roadClass="FEDERAL" routeRef="1" onDark />
              <RoutePlate roadClass="STATE" routeRef="A15" onDark />
              <RoutePlate roadClass="EXPRESSWAY" routeRef="E2" onDark />
            </div>
            <p className="mt-6 font-condensed text-4xl leading-tight font-semibold">{t('auth.panelTitle')}</p>
            <p className="mt-3 text-lg text-kerb/80">{t('auth.panelBody')}</p>
          </div>
        </aside>
      </div>
    </GuestOnly>
  )
}
