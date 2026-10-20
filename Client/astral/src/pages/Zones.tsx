import { useQueries, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'

import { useApi } from '../app/auth'
import { useScope } from '../app/scope'
import { HazardIcon } from '../components/ui/HazardIcon'
import { RoutePlate } from '../components/ui/RoutePlate'
import { ErrorBox, Loading } from '../components/ui/Status'
import { formatNumber } from '../lib/format'
import { HAZARD_TYPES, HAZARDS } from '../lib/hazards'
import type { District, ZoneSummary } from '../lib/types'

// State → District (FR-ZON-01): one ledger row per district, the same structure as the ranking.
function HazardCounts({ counts }: { counts: ZoneSummary['open_incidents'] }) {
  const { t } = useTranslation()
  return (
    <span className="flex flex-wrap gap-3 text-sm">
      {HAZARD_TYPES.map((h) => (
        <span key={h} className="inline-flex items-center gap-1" title={t(HAZARDS[h].labelKey)}>
          <HazardIcon type={h} size={16} /><span className="sr-only">{t(HAZARDS[h].labelKey)}</span>
          <span className="tabular">{formatNumber(counts[h])}</span>
        </span>
      ))}
    </span>
  )
}

function DistrictList() {
  const { t } = useTranslation()
  const api = useApi()
  const [scope] = useScope()
  const state = scope.state || 'A'
  const districts = useQuery({
    queryKey: ['districts', state],
    queryFn: () => api<District[]>('/meta/districts', { params: { state } }),
  })
  const summaries = useQueries({
    queries: (districts.data ?? []).map((d) => ({
      queryKey: ['zone', d.id],
      queryFn: () => api<ZoneSummary>(`/zones/${d.id}/summary`),
    })),
  })
  if (districts.isPending) return <Loading />
  if (districts.isError) return <ErrorBox error={districts.error} onRetry={() => districts.refetch()} />
  const rows = (districts.data ?? []).map((d, i) => ({ d, s: summaries[i]?.data }))
  rows.sort((a, b) => (b.s?.overdue_sla ?? -1) - (a.s?.overdue_sla ?? -1))

  return (
    <>
      <p className="max-w-prose text-road">{t('zones.intro')}</p>
      <div className="mt-6 border-y border-hairline bg-kerb">
        <div aria-hidden="true" className="hidden grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_6rem_6rem_minmax(0,1.6fr)] gap-x-4 border-b border-hairline px-4 py-2 text-sm text-road md:grid">
          <span>{t('zones.district')}</span><span>{t('zones.open')}</span><span>{t('zones.overdue')}</span>
          <span>{t('zones.highRisk')}</span><span>{t('zones.topRoad')}</span>
        </div>
        <ul>
          {rows.map(({ d, s }) => (
            <li key={d.id} className="border-b border-hairline last:border-b-0">
              <Link to={`/zones/${d.id}`} className="grid gap-x-4 gap-y-1 px-4 py-3 hover:bg-concrete md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_6rem_6rem_minmax(0,1.6fr)] md:items-center">
                <span className="font-condensed text-lg font-semibold">{d.name}</span>
                {s ? (
                  <>
                    <HazardCounts counts={s.open_incidents} />
                    <span className={`tabular ${s.overdue_sla > 0 ? 'font-semibold text-overdue' : ''}`}>
                      <span className="md:sr-only">{t('zones.overdue')}: </span>{formatNumber(s.overdue_sla)}
                    </span>
                    <span className="tabular"><span className="md:sr-only">{t('zones.highRisk')}: </span>{formatNumber(s.high_risk_segments)}</span>
                    <span className="truncate text-sm">{s.top_roads[0] ? `${s.top_roads[0].name ?? t('common.unnamedRoad')} (${formatNumber(s.top_roads[0].score, 1)})` : '—'}</span>
                  </>
                ) : <span className="text-sm text-road md:col-span-4">{t('app.loading')}</span>}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </>
  )
}

// Special zones (FR-ZON-02): karst and ex-mining ground, which raise sinkhole risk.
const SPECIAL_TYPES = ['KARST', 'EX_MINING'] as const
type ZoneRow = { id: string; type: string; name: string }

function SpecialZones() {
  const { t } = useTranslation()
  const api = useApi()
  const lists = useQueries({
    queries: SPECIAL_TYPES.map((type) => ({
      queryKey: ['zones', type],
      queryFn: () => api<ZoneRow[]>('/zones', { params: { type } }),
      staleTime: 3_600_000,
    })),
  })
  const zones = lists.flatMap((l) => l.data ?? [])
  if (zones.length === 0) return null
  return (
    <section className="mt-10" aria-labelledby="special-zones">
      <h2 id="special-zones" className="text-lg font-semibold">{t('zones.special')}</h2>
      <p className="mt-1 max-w-prose text-sm text-road">{t('zones.specialIntro')}</p>
      <ul className="mt-3 border-y border-hairline bg-kerb">
        {zones.map((z) => (
          <li key={z.id} className="border-b border-hairline last:border-b-0">
            <Link to={`/zones/${z.id}`} className="flex flex-wrap items-baseline justify-between gap-x-4 px-4 py-3 hover:bg-concrete">
              <span className="font-condensed text-lg font-semibold">{z.name}</span>
              <span className="text-sm text-road">{t(`zones.type.${z.type}`)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ZoneDetail({ id }: { id: string }) {
  const { t } = useTranslation()
  const api = useApi()
  const q = useQuery({ queryKey: ['zone', id], queryFn: () => api<ZoneSummary>(`/zones/${id}/summary`) })
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />
  const z = q.data
  return (
    <article>
      <Link to="/zones" className="text-sm underline underline-offset-4">{t('zones.all')}</Link>
      <h1 className="mt-2 text-2xl font-semibold">{z.zone.name}</h1>
      <dl className="mt-4 flex flex-wrap gap-8">
        <div className="flex flex-col"><dt className="order-2 text-sm text-road">{t('zones.open')}</dt><dd className="order-1"><HazardCounts counts={z.open_incidents} /></dd></div>
        <div className="flex flex-col"><dt className="order-2 text-sm text-road">{t('zones.overdue')}</dt><dd className={`order-1 font-condensed text-2xl font-semibold ${z.overdue_sla ? 'text-overdue' : ''}`}>{formatNumber(z.overdue_sla)}</dd></div>
        <div className="flex flex-col"><dt className="order-2 text-sm text-road">{t('zones.highRisk')}</dt><dd className="order-1 font-condensed text-2xl font-semibold">{formatNumber(z.high_risk_segments)}</dd></div>
        <div className="flex flex-col"><dt className="order-2 text-sm text-road">{t('zones.segments')}</dt><dd className="order-1 font-condensed text-2xl font-semibold">{formatNumber(z.segments)}</dd></div>
      </dl>
      <h2 className="mt-8 text-lg font-semibold">{t('zones.top5')}</h2>
      <ol className="mt-3 border-y border-hairline bg-kerb">
        {z.top_roads.map((r, i) => (
          <li key={r.segment_id} className="border-b border-hairline last:border-b-0">
            <Link to={`/analysis/${r.segment_id}`} className="grid grid-cols-[2rem_1fr_auto] items-start gap-3 px-4 py-3 hover:bg-concrete">
              <span className="font-condensed text-xl font-semibold text-road">{i + 1}</span>
              <span className="min-w-0">
                <span className="flex items-center gap-2"><RoutePlate roadClass={r.road_class} routeRef={r.ref} /><span className="font-condensed text-lg font-semibold">{r.name ?? t('common.unnamedRoad')}</span></span>
                <span className="block text-sm">{r.recommended_action ?? ''}</span>
                <span className="block text-sm text-road">{r.owner}</span>
              </span>
              <span className="font-condensed text-xl font-semibold tabular">{formatNumber(r.score, 1)}</span>
            </Link>
          </li>
        ))}
      </ol>
      {z.agencies.length > 0 && (
        <>
          <h2 className="mt-8 text-lg font-semibold">{t('zones.agencies')}</h2>
          <p className="mt-2 max-w-prose">{z.agencies.join(', ')}</p>
        </>
      )}
    </article>
  )
}

export default function Zones() {
  const { t } = useTranslation()
  const { zoneId } = useParams()
  return (
    <div className="max-w-5xl px-4 py-8 sm:px-8">
      {zoneId ? <ZoneDetail id={zoneId} /> : (
        <>
          <h1 className="mb-2 text-2xl font-semibold">{t('nav.zones')}</h1>
          <DistrictList />
          <SpecialZones />
        </>
      )}
    </div>
  )
}
