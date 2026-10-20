import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { GuestOnly } from '../app/guards'
import { buttonClass } from '../components/ui/Button'
import { HazardIcon } from '../components/ui/HazardIcon'
import { RoutePlate } from '../components/ui/RoutePlate'
import { HAZARD_TYPES, HAZARDS } from '../lib/hazards'

const CENTRE_LINE = 'repeating-linear-gradient(to bottom, var(--color-marking) 0 44px, transparent 44px 80px)'

/** First page for signed-out visitors: what the product is, then one way in per audience (DESIGN.md). */
export default function Landing() {
  const { t } = useTranslation()
  const paths = [
    { key: 'report', to: '/report', variant: 'primary' as const },
    { key: 'map', to: '/map', variant: 'secondary' as const },
    { key: 'staff', to: '/sign-in', variant: 'secondary' as const },
  ]

  return (
    <GuestOnly>
      <div className="min-h-full bg-concrete lg:grid lg:grid-cols-[1fr_1.1fr]">
        <section className="relative flex flex-col justify-between overflow-hidden bg-asphalt px-6 py-8 text-kerb sm:px-12 sm:py-12">
          <div className="absolute inset-y-0 left-[82%] hidden w-1.5 lg:block" aria-hidden="true"
            style={{ background: CENTRE_LINE }} />
          <div className="relative">
            <p className="font-condensed text-2xl font-semibold">{t('app.name')}</p>
            <p className="mt-1 text-kerb/75">{t('landing.tagline')}</p>
          </div>

          <div className="relative my-10 max-w-md">
            <div className="flex gap-2">
              <RoutePlate roadClass="FEDERAL" routeRef="1" onDark />
              <RoutePlate roadClass="STATE" routeRef="A15" onDark />
              <RoutePlate roadClass="EXPRESSWAY" routeRef="E2" onDark />
            </div>
            <h1 className="mt-6 font-condensed text-4xl leading-tight font-semibold">{t('landing.title')}</h1>
            <p className="mt-3 text-lg text-kerb/80">{t('landing.body')}</p>

            {/* Hidden on phones so the ways in stay near the top for people reporting outdoors. */}
            <h2 className="mt-8 hidden text-sm font-semibold text-kerb/75 sm:block">{t('landing.hazardsLabel')}</h2>
            <ul className="mt-3 hidden space-y-3 sm:block">
              {HAZARD_TYPES.map((type) => (
                <li key={type} className="flex items-start gap-3">
                  <HazardIcon type={type} size={28} />
                  <span>
                    <span className="font-semibold">{t(HAZARDS[type].labelKey)}</span>
                    <span className="block text-sm text-kerb/75">{t(`landing.hazard.${type}`)}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <p className="relative text-xs text-kerb/60">{t('landing.coverage')}</p>
        </section>

        <main className="flex items-center px-6 py-10 sm:px-12 lg:py-14">
          <div className="w-full max-w-sm">
            <h2 className="text-2xl font-semibold">{t('landing.choose')}</h2>
            <ul className="mt-6 divide-y divide-hairline border-y border-hairline">
              {paths.map((p) => (
                <li key={p.key} className="py-5">
                  <h3 className="text-lg font-semibold">{t(`landing.${p.key}.title`)}</h3>
                  <p className="mt-1 text-road">{t(`landing.${p.key}.body`)}</p>
                  <Link to={p.to} className={buttonClass(p.variant, 'mt-3 w-full')}>{t(`landing.${p.key}.action`)}</Link>
                </li>
              ))}
            </ul>
            <p className="mt-6 text-sm text-road">
              {t('auth.newHere')}{' '}
              <Link to="/register" className="font-medium text-asphalt underline underline-offset-4">{t('auth.createAccount')}</Link>
            </p>
          </div>
        </main>
      </div>
    </GuestOnly>
  )
}
