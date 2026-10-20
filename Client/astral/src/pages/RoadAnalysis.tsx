import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { useApi } from '../app/auth'
import { BreakdownBar } from '../components/priority/BreakdownBar'
import { Button, buttonClass } from '../components/ui/Button'
import { HazardLabel } from '../components/ui/HazardIcon'
import { RoutePlate } from '../components/ui/RoutePlate'
import { EmptyState, ErrorBox, Loading } from '../components/ui/Status'
import { Term } from '../components/ui/Term'
import { factorLabel } from '../lib/factors'
import { formatMonth, formatNumber } from '../lib/format'
import { HAZARDS } from '../lib/hazards'
import type { PriorityItem, SearchResult, SegmentAnalysis } from '../lib/types'

const AXIS = { fontSize: 12, fill: '#5A6168' }
const GRID = '#D6DADB'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-hairline pt-6">
      <h2 className="mb-3 text-lg font-semibold">{title}</h2>
      {children}
    </section>
  )
}

function Stat({ value, label }: { value: string; label: ReactNode }) {
  return (
    <div className="flex flex-col">
      <dt className="order-2 text-sm text-road">{label}</dt>
      <dd className="order-1 font-condensed text-2xl font-semibold tabular">{value}</dd>
    </div>
  )
}

function Search() {
  const { t } = useTranslation()
  const api = useApi()
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [term, setTerm] = useState('')
  useEffect(() => {
    const id = window.setTimeout(() => setTerm(q.trim()), 300)
    return () => window.clearTimeout(id)
  }, [q])
  const results = useQuery({
    queryKey: ['segment-search', term],
    queryFn: () => api<{ items: SearchResult[] }>('/segments/search', { params: { q: term } }),
    enabled: term.length >= 2,
  })
  return (
    <div className="max-w-xl">
      <label htmlFor="road-search" className="block font-semibold">{t('analysis.searchLabel')}</label>
      <input id="road-search" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('analysis.searchPlaceholder')}
        className="mt-1 block min-h-11 w-full rounded border border-road bg-kerb px-3" autoComplete="off" />
      {results.isError && <div className="mt-3"><ErrorBox error={results.error} /></div>}
      {results.data && (results.data.items.length === 0 ? (
        <p className="mt-3 text-road">{t('analysis.noMatches')}</p>
      ) : (
        <ul className="mt-3 border-y border-hairline bg-kerb">
          {results.data.items.map((r) => (
            <li key={r.segment_id} className="border-b border-hairline last:border-b-0">
              <button type="button" onClick={() => navigate(`/analysis/${r.segment_id}`)}
                className="flex min-h-14 w-full items-center gap-3 px-4 py-2 text-left hover:bg-concrete">
                <RoutePlate roadClass={r.road_class} routeRef={r.ref} />
                <span className="min-w-0 flex-1">
                  <span className="block font-condensed text-lg font-semibold">{r.name ?? t('common.unnamedRoad')}</span>
                  <span className="block text-sm text-road">{r.district}, {r.state.name}, {t('analysis.km', { km: formatNumber(r.length_km, 1) })}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      ))}
    </div>
  )
}

function AiSummary({ segmentId }: { segmentId: number }) {
  const { t, i18n } = useTranslation()
  const api = useApi()
  const explain = useMutation({
    mutationFn: () => api<{ text: string; ai_suggested: boolean; cached: boolean }>('/ai/explain', {
      method: 'POST', body: { segment_id: segmentId, language: i18n.language === 'ms' ? 'ms' : 'en' } }),
  })
  return (
    <div className="border-l-4 border-marking bg-kerb p-4">
      {explain.data ? (
        <>
          <p className="text-sm font-semibold">{explain.data.ai_suggested ? t('analysis.aiSuggested') : t('analysis.summaryTemplate')}</p>
          <p className="mt-1 max-w-prose">{explain.data.text}</p>
        </>
      ) : (
        <>
          <p className="max-w-prose text-road">{t('analysis.aiIntro')}</p>
          {explain.isError && <div className="mt-2"><ErrorBox error={explain.error} /></div>}
          <Button className="mt-3" onClick={() => explain.mutate()} disabled={explain.isPending}>
            {explain.isPending ? t('analysis.writing') : t('analysis.explain')}
          </Button>
        </>
      )}
    </div>
  )
}

function Analysis({ id }: { id: number }) {
  const { t } = useTranslation()
  const api = useApi()
  const q = useQuery({ queryKey: ['analysis', id], queryFn: () => api<SegmentAnalysis>(`/segments/${id}/analysis`) })
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />
  const a = q.data
  const months = a.pothole_frequency.series.map((m, i) => ({
    month: formatMonth(m.month), potholes: m.count,
    trees: a.natural_events.series[i]?.fallen_tree ?? 0, sinkholes: a.natural_events.series[i]?.sinkhole ?? 0,
    warnings: a.natural_events.series[i]?.weather_warnings ?? 0, floods: a.natural_events.series[i]?.flood_warnings ?? 0,
  }))
  const p = a.priority
  const asItem = p ? ({ components: p.components } as PriorityItem) : null

  return (
    <article className="space-y-8">
      <header>
        <p className="flex flex-wrap items-center gap-2">
          <RoutePlate roadClass={a.road_class} routeRef={a.ref} />
          <span className="font-condensed text-4xl leading-tight font-semibold">{a.name ?? t('common.unnamedRoad')}</span>
        </p>
        <p className="mt-1 text-road">{t(`roadClass.${a.road_class}`)}, {a.district}, {a.state.name}, {t('analysis.km', { km: formatNumber(a.length_km, 2) })}</p>
        <dl className="mt-4 grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
          <div><dt className="text-road">{t('drawer.owner')}</dt><dd className="font-medium">{a.owner}</dd></div>
          <div><dt className="text-road">{t('drawer.maintainer')}</dt><dd className="font-medium">{a.maintainer}</dd></div>
        </dl>
        <div className="mt-4 flex flex-wrap gap-3">
          <Link to={`/map?segment=${a.segment_id}`} className={buttonClass('secondary')}>{t('analysis.showOnMap')}</Link>
        </div>
      </header>

      {p && asItem && (
        <Section title={t('analysis.priority')}>
          <div className="flex flex-wrap items-end gap-6">
            <dl><Stat value={formatNumber(p.score, 1)} label={t('analysis.score')} /></dl>
            <dl><Stat value={`#${p.rank_in_district}`} label={t('analysis.rankInDistrict', { district: a.district })} /></dl>
            <div className="min-w-48 flex-1"><BreakdownBar item={asItem} /></div>
          </div>
          {p.recommended_action && <p className="mt-3 font-medium">{p.recommended_action}</p>}
          {p.refer_to.length > 0 && <p className="text-sm text-road">{t('priority.referTo', { agencies: p.refer_to.join(', ') })}</p>}
        </Section>
      )}

      <Section title={t('analysis.aiTitle')}><AiSummary segmentId={a.segment_id} /></Section>

      <Section title={t('analysis.potholes')}>
        <dl className="mb-4 flex flex-wrap gap-8">
          <Stat value={formatNumber(a.pothole_frequency.per_km_per_month, 2)} label={t('analysis.perKmMonth')} />
          <Stat value={a.pothole_frequency.recurrence_days === null ? '—' : t('analysis.days', { count: a.pothole_frequency.recurrence_days })} label={t('analysis.recurrence')} />
        </dl>
        <div className="h-56" role="img" aria-label={t('analysis.potholesChart')}>
          <ResponsiveContainer>
            <BarChart data={months} margin={{ left: -20, right: 8 }}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="month" tick={AXIS} tickLine={false} />
              <YAxis allowDecimals={false} tick={AXIS} tickLine={false} axisLine={false} />
              <Tooltip />
              <Bar dataKey="potholes" name={t('hazard.POTHOLE')} fill={HAZARDS.POTHOLE.color} radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Section>

      <Section title={t('analysis.traffic')}>
        <dl className="flex flex-wrap gap-8">
          <Stat value={formatNumber(a.traffic.adt)} label={<Term name="ADT">{t('analysis.adt')}</Term>} />
          <Stat value={a.traffic.heavy_pct === null ? '—' : `${Math.round(a.traffic.heavy_pct * 100)}%`} label={t('analysis.heavy')} />
        </dl>
        <p className="mt-2 text-sm text-road">{a.traffic.estimated ? t('analysis.adtEstimated') : t('analysis.adtSource', { source: a.traffic.adt_source })}</p>
        {a.traffic.congestion_series.length > 0 && (
          <div className="mt-4 h-44" role="img" aria-label={t('analysis.congestionChart')}>
            <ResponsiveContainer>
              <LineChart data={a.traffic.congestion_series} margin={{ left: -20, right: 8 }}>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="date" tick={AXIS} tickLine={false} />
                <YAxis domain={[0, 1]} tick={AXIS} tickLine={false} axisLine={false} />
                <Tooltip />
                <Line dataKey="avg_ratio" name={t('analysis.speedRatio')} stroke="#2E3236" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </Section>

      <Section title={t('analysis.natural')}>
        <div className="h-56" role="img" aria-label={t('analysis.naturalChart')}>
          <ResponsiveContainer>
            <BarChart data={months} margin={{ left: -20, right: 8 }}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="month" tick={AXIS} tickLine={false} />
              <YAxis allowDecimals={false} tick={AXIS} tickLine={false} axisLine={false} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 13 }} />
              <Bar dataKey="trees" stackId="h" name={t('hazard.FALLEN_TREE')} fill={HAZARDS.FALLEN_TREE.color} />
              <Bar dataKey="sinkholes" stackId="h" name={t('hazard.SINKHOLE')} fill={HAZARDS.SINKHOLE.color} />
              <Bar dataKey="warnings" name={t('analysis.weatherWarnings')} fill="#5A6168" />
              {a.natural_events.flood_available && <Bar dataKey="floods" name={t('analysis.floodWarnings')} fill="#3A6EA5" />}
            </BarChart>
          </ResponsiveContainer>
        </div>
        {!a.natural_events.flood_available && <p className="mt-2 text-sm text-road">{t('analysis.floodNotYet')}</p>}
        {a.weather && (
          <p className="mt-3 text-sm">{t('analysis.rain', { d7: formatNumber(a.weather.rain_7d, 0), d30: formatNumber(a.weather.rain_30d, 0), next: formatNumber(a.weather.forecast_7d, 0) })}</p>
        )}
      </Section>

      <Section title={t('analysis.safety')}>
        <dl className="flex flex-wrap gap-8">
          <Stat value={formatNumber(a.safety.deaths_3y)} label={t('analysis.deaths')} />
          <Stat value={formatNumber(a.safety.injuries_3y)} label={t('analysis.injuries')} />
        </dl>
        {a.safety.sources.length > 0 && (
          <p className="mt-2 text-sm text-road">
            {t('analysis.sources')}{' '}
            {a.safety.sources.map((s, i) => (
              <span key={i}>{i > 0 && ', '}{s.url ? <a href={s.url} className="underline" target="_blank" rel="noreferrer">{t(`source.${s.type}`)}</a> : t(`source.${s.type}`)}</span>
            ))}
          </p>
        )}
      </Section>

      <Section title={t('analysis.predictions')}>
        {a.predictions.length === 0 ? <p className="text-road">{t('analysis.noPredictions')}</p> : (
          <ul className="divide-y divide-hairline border-y border-hairline bg-kerb">
            {a.predictions.filter((x) => x.horizon_days === 30).map((x) => (
              <li key={x.hazard_type} className="grid gap-1 px-4 py-3 sm:grid-cols-[12rem_8rem_1fr] sm:items-baseline">
                <HazardLabel type={x.hazard_type} />
                <span className="font-semibold tabular">{Math.round(x.probability * 100)}%, {t(`risk.${x.risk_level}`).toLowerCase()}</span>
                <span className="text-sm text-road">{x.top_factors.slice(0, 3).map((f) => factorLabel(f, t)).join('; ')}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-sm text-road">{t('analysis.horizonNote')}</p>
      </Section>
    </article>
  )
}

export default function RoadAnalysis() {
  const { t } = useTranslation()
  const { segmentId } = useParams()
  const id = segmentId ? Number(segmentId) : null
  return (
    <div className="max-w-4xl px-4 py-8 sm:px-8">
      <h1 className="mb-6 text-2xl font-semibold">{t('nav.analysis')}</h1>
      <Search />
      <div className="mt-8">
        {id ? <Analysis id={id} /> : <EmptyState title={t('analysis.emptyTitle')} body={t('analysis.emptyBody')} />}
      </div>
    </div>
  )
}
