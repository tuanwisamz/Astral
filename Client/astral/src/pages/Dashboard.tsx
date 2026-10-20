import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { useApi } from '../app/auth'
import { useScope } from '../app/scope'
import { buttonClass } from '../components/ui/Button'
import { HazardIcon } from '../components/ui/HazardIcon'
import { RoutePlate } from '../components/ui/RoutePlate'
import { ErrorBox, Loading } from '../components/ui/Status'
import { formatNumber } from '../lib/format'
import { HAZARD_TYPES, HAZARDS } from '../lib/hazards'
import type { DashboardSummary, District, StateInfo } from '../lib/types'

function useScopeName(): string | null {
  const api = useApi()
  const [scope] = useScope()
  const states = useQuery({ queryKey: ['states'], queryFn: () => api<StateInfo[]>('/meta/states') })
  const districts = useQuery({
    queryKey: ['districts', scope.state],
    queryFn: () => api<District[]>('/meta/districts', { params: { state: scope.state } }),
    enabled: Boolean(scope.state),
  })
  const state = states.data?.find((s) => s.code === scope.state)?.name
  const district = districts.data?.find((d) => d.id === scope.district)?.name
  if (!state) return null
  return district ? `${district}, ${state}` : state
}

export default function Dashboard() {
  const { t } = useTranslation()
  const api = useApi()
  const [scope] = useScope()
  const place = useScopeName()
  const q = useQuery({
    queryKey: ['dashboard', scope],
    queryFn: () => api<DashboardSummary>('/dashboard/summary', { params: { ...scope } }),
  })
  const openTotal = q.data ? HAZARD_TYPES.reduce((sum, h) => sum + q.data.open_incidents[h], 0) : 0

  return (
    <div className="max-w-5xl px-4 py-8 sm:px-8">
      <h1 className="text-2xl font-semibold">{t('dashboard.title')}</h1>
      <p className="mt-1 text-road">{place ? t('dashboard.scopeIn', { place }) : t('dashboard.scopeAll')}</p>

      {q.isPending && <div className="mt-8"><Loading /></div>}
      {q.isError && <div className="mt-8"><ErrorBox error={q.error} onRetry={() => q.refetch()} /></div>}
      {q.data && (
        <>
          <ol className="mt-6 border-y border-hairline bg-kerb">
            {q.data.top_roads.slice(0, 5).map((road, i) => (
              <li key={road.segment_id}
                className="relative grid grid-cols-[2.5rem_1fr_auto] items-start gap-x-4 border-b border-hairline px-4 py-4 last:border-b-0 sm:px-6">
                {i === 0 && <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1.5 bg-marking" />}
                <span className="font-condensed text-2xl leading-none font-semibold text-road tabular">{i + 1}</span>
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2">
                    <RoutePlate roadClass={road.road_class} routeRef={road.ref} />
                    <span className="font-condensed text-xl leading-tight font-semibold">{road.name ?? t('common.unnamedRoad')}</span>
                  </p>
                  {road.recommended_action && <p className="mt-1">{road.recommended_action}</p>}
                  <p className="mt-0.5 text-sm text-road">{road.owner}, {road.district}</p>
                </div>
                <span className="font-condensed text-2xl leading-none font-semibold tabular"
                  aria-label={t('dashboard.score', { score: road.score.toFixed(1) })}>
                  {road.score.toFixed(1)}
                </span>
              </li>
            ))}
          </ol>
          <Link to="/priority" className={buttonClass('quiet', 'mt-2 px-0')}>{t('dashboard.seeAll')}</Link>

          <dl aria-label={t('dashboard.keyFigures')}
            className="mt-8 grid grid-cols-2 gap-y-6 border-t border-hairline pt-6 sm:grid-cols-4 sm:divide-x sm:divide-hairline">
            <div className="flex flex-col pr-4">
              <dt className="order-2 text-sm text-road">{t('dashboard.openIncidents')}</dt>
              <dd className="order-1 font-condensed text-2xl font-semibold tabular">{formatNumber(openTotal)}</dd>
              <dd className="order-3 mt-2 flex flex-wrap gap-3 text-sm">
                {HAZARD_TYPES.map((h) => (
                  <span key={h} className="inline-flex items-center gap-1" title={t(HAZARDS[h].labelKey)}>
                    <HazardIcon type={h} size={16} />
                    <span className="sr-only">{t(HAZARDS[h].labelKey)}</span>
                    <span className="tabular">{formatNumber(q.data.open_incidents[h])}</span>
                  </span>
                ))}
              </dd>
            </div>
            {([
              ['overdue_sla', 'dashboard.overdueSla', true],
              ['active_warnings', 'dashboard.activeWarnings', false],
              ['high_risk_segments', 'dashboard.highRisk', false],
            ] as const).map(([key, label, critical]) => (
              <div key={key} className="flex flex-col sm:px-6">
                <dt className="order-2 text-sm text-road">{t(label)}</dt>
                <dd className={`order-1 font-condensed text-2xl font-semibold tabular ${critical && q.data[key] > 0 ? 'text-overdue' : ''}`}>
                  {formatNumber(q.data[key])}
                </dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </div>
  )
}
