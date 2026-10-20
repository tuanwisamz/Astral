import 'leaflet/dist/leaflet.css'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import L from 'leaflet'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { MapContainer, Polyline, TileLayer, useMap } from 'react-leaflet'

import { useApi, useAuthState } from '../app/auth'
import { useScope } from '../app/scope'
import { BreakdownBar, COMPONENT_COLORS } from '../components/priority/BreakdownBar'
import { Button } from '../components/ui/Button'
import { RoutePlate } from '../components/ui/RoutePlate'
import { ErrorBox, Loading } from '../components/ui/Status'
import { useToast } from '../components/ui/Toast'
import i18n from '../i18n'
import { formatNumber } from '../lib/format'
import type { Component, LineString, PriorityItem, PriorityList } from '../lib/types'

const TILE_URL: string = import.meta.env.VITE_MAP_TILE_URL ?? 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const COMPONENTS = Object.keys(COMPONENT_COLORS) as Component[]
const COLUMNS = 'md:grid-cols-[4.75rem_minmax(0,1.3fr)_minmax(0,1fr)_4.5rem_11rem_minmax(0,1.4fr)]'
const listFormat = (items: string[]) => new Intl.ListFormat(i18n.language === 'ms' ? 'ms' : 'en', { type: 'conjunction' }).format(items)
type Item = PriorityItem & { geometry?: LineString }

function Fit({ items }: { items: Item[] }) {
  const map = useMap()
  const key = items.map((i) => i.segment_id).join(',')
  useEffect(() => {
    const pts = items.flatMap((i) => i.geometry?.coordinates.map(([lng, lat]) => [lat, lng] as [number, number]) ?? [])
    if (pts.length) map.fitBounds(L.latLngBounds(pts), { padding: [24, 24], maxZoom: 15 })
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- refit when the set of roads changes, not on every render
  }, [map, key])
  return null
}

/** Linked to the table (FR-PR-06): hovering a row lights its road, and the other way round. */
function MiniMap({ items, hovered, onHover, onOpen }: { items: Item[]; hovered: number | null; onHover: (id: number | null) => void; onOpen: (id: number) => void }) {
  const { t } = useTranslation()
  return (
    <div className="h-72 overflow-hidden rounded border border-hairline lg:sticky lg:top-4 lg:h-[calc(100vh-12rem)]" aria-label={t('priority.miniMap')}>
      <MapContainer center={[4.6, 101.1]} zoom={11} preferCanvas className="h-full w-full" scrollWheelZoom={false}>
        <TileLayer url={TILE_URL} attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' />
        <Fit items={items} />
        {items.map((i) => i.geometry && (
          <Polyline key={i.segment_id} positions={i.geometry.coordinates.map(([lng, lat]) => [lat, lng] as [number, number])}
            pathOptions={{ color: hovered === i.segment_id ? '#F5C400' : '#2E3236', weight: hovered === i.segment_id ? 10 : 5, opacity: hovered === null || hovered === i.segment_id ? 0.95 : 0.35 }}
            eventHandlers={{ mouseover: () => onHover(i.segment_id), mouseout: () => onHover(null), click: () => onOpen(i.segment_id) }} />
        ))}
      </MapContainer>
    </div>
  )
}

/** What-if (T6.8): drag a weight and the ranking re-sorts; weights always add up to 100%. */
function WeightSliders({ weights, onChange, onReset, onSave, canSave }: {
  weights: Record<Component, number>; onChange: (w: Record<Component, number>) => void; onReset: () => void; onSave: () => void; canSave: boolean
}) {
  const { t } = useTranslation()
  const total = COMPONENTS.reduce((s, c) => s + weights[c], 0) || 1
  return (
    <fieldset className="border-y border-hairline bg-kerb p-4">
      <legend className="sr-only">{t('priority.whatIf')}</legend>
      <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
        {COMPONENTS.map((c) => (
          <label key={c} className="block text-sm">
            <span className="flex items-center justify-between gap-2">
              <span className="inline-flex items-center gap-2"><span aria-hidden="true" className="h-3 w-3 rounded-sm" style={{ background: COMPONENT_COLORS[c] }} />{t(`priority.components.${c}`)}</span>
              <span className="tabular font-semibold">{Math.round((weights[c] / total) * 100)}%</span>
            </span>
            <input type="range" min={0} max={100} step={1} value={Math.round(weights[c] * 100)} className="mt-1 w-full accent-[#2E3236]"
              onChange={(e) => onChange({ ...weights, [c]: Number(e.target.value) / 100 })} />
          </label>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button onClick={onReset}>{t('priority.resetWeights')}</Button>
        {canSave && <Button variant="quiet" onClick={onSave}>{t('priority.saveDefault')}</Button>}
      </div>
    </fieldset>
  )
}

export default function Priority() {
  const { t } = useTranslation()
  const api = useApi()
  const auth = useAuthState()
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  const [scope] = useScope()
  const [hovered, setHovered] = useState<number | null>(null)
  const [whatIf, setWhatIf] = useState(false)
  const [weights, setWeights] = useState<Record<Component, number> | null>(null)
  const [debounced, setDebounced] = useState<Record<Component, number> | null>(null)
  const canSimulate = auth.role === 'officer' || auth.role === 'admin' || auth.role === 'dev'

  const base = useQuery({
    queryKey: ['priority', scope],
    queryFn: () => api<PriorityList>('/priority', { params: { ...scope, limit: 50 } }),
  })
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(weights), 250)
    return () => window.clearTimeout(id)
  }, [weights])
  const sim = useQuery({
    queryKey: ['simulate', scope, debounced],
    queryFn: () => api<PriorityList>('/priority/simulate', { method: 'POST', body: { scope, weights: debounced, limit: 50 } }),
    enabled: whatIf && debounced !== null,
    placeholderData: (prev) => prev,
  })
  const saveDefault = useMutation({
    mutationFn: () => api(`/priority/profiles/${base.data?.profile.id}`, { method: 'PUT', body: { weights } }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['priority'] }); toast(t('priority.savedDefault')) },
  })

  const data = whatIf && sim.data ? sim.data : base.data
  const items = useMemo(() => (data?.items ?? []) as Item[], [data])
  const ids = useMemo(() => items.map((i) => i.segment_id), [items])

  async function downloadCsv() {
    const res = await api<Response>('/priority/export', { params: { ...scope }, raw: true })
    const blob = await res.blob()
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `priority-${new Date().toISOString().slice(0, 10)}.csv` })
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="px-4 py-8 sm:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{t('priority.title')}</h1>
          <p className="mt-1 max-w-prose text-road">{t('priority.intro')}</p>
        </div>
        <div className="flex flex-wrap gap-2 print:hidden">
          {canSimulate && (
            <Button aria-pressed={whatIf} onClick={() => { setWhatIf(!whatIf); if (!weights && base.data) setWeights(base.data.profile.weights) }}>
              {whatIf ? t('priority.closeWhatIf') : t('priority.whatIf')}
            </Button>
          )}
          {canSimulate && <Button onClick={() => void downloadCsv()}>{t('priority.exportCsv')}</Button>}
          <Button variant="quiet" onClick={() => window.print()}>{t('priority.print')}</Button>
        </div>
      </div>

      {whatIf && weights && (
        <div className="mt-6 print:hidden">
          <WeightSliders weights={weights} onChange={setWeights} canSave={auth.role === 'admin' || auth.role === 'dev'}
            onReset={() => setWeights(base.data!.profile.weights)} onSave={() => saveDefault.mutate()} />
          {sim.isFetching && <p className="mt-2 text-sm text-road" aria-live="polite">{t('priority.reranking')}</p>}
        </div>
      )}

      {base.isPending && <div className="mt-8"><Loading /></div>}
      {(base.isError || sim.isError) && <div className="mt-8"><ErrorBox error={base.error ?? sim.error} onRetry={() => base.refetch()} /></div>}
      {data && (
        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div>
            <ul aria-label={t('priority.weightsLabel')} className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
              {COMPONENTS.map((k) => (
                <li key={k} className="inline-flex items-center gap-2">
                  <span aria-hidden="true" className="inline-block h-3 w-3 rounded-sm" style={{ background: COMPONENT_COLORS[k] }} />
                  {t(`priority.components.${k}`)}<span className="text-road tabular">{Math.round(data.profile.weights[k] * 100)}%</span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-sm text-road">{t('priority.total', { count: data.total })}</p>
            <div className="mt-4 border-y border-hairline bg-kerb">
              <div aria-hidden="true" className={`hidden gap-x-4 border-b border-hairline px-4 py-2 text-sm text-road md:grid ${COLUMNS}`}>
                <span>{t('priority.rank')}</span><span>{t('priority.road')}</span><span>{t('priority.owner')}</span>
                <span className="text-right">{t('priority.score')}</span><span>{t('priority.breakdown')}</span><span>{t('priority.action')}</span>
              </div>
              <ol>
                {items.map((item) => (
                  <li key={item.segment_id} onMouseEnter={() => setHovered(item.segment_id)} onMouseLeave={() => setHovered(null)}
                    className={`relative border-b border-hairline last:border-b-0 ${hovered === item.segment_id ? 'bg-concrete' : ''}`}>
                    <button type="button" onClick={() => navigate(`/analysis/${item.segment_id}`)} onFocus={() => setHovered(item.segment_id)} onBlur={() => setHovered(null)}
                      className={`grid w-full grid-cols-[2.5rem_1fr_auto] gap-x-4 gap-y-2 px-4 py-4 text-left md:items-center ${COLUMNS}`}>
                      {item.rank === 1 && <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1.5 bg-marking" />}
                      <span className="font-condensed text-xl font-semibold text-road tabular">
                        {item.rank}
                        {item.rank_change ? <span className={`ml-1 text-sm ${item.rank_change > 0 ? 'text-asphalt' : 'text-road'}`}>{item.rank_change > 0 ? `▲${item.rank_change}` : `▼${-item.rank_change}`}</span> : null}
                      </span>
                      <span className="min-w-0">
                        <span className="flex flex-wrap items-center gap-2">
                          <RoutePlate roadClass={item.road_class} routeRef={item.ref} />
                          <span className="font-condensed text-lg leading-tight font-semibold">{item.name ?? t('common.unnamedRoad')}</span>
                        </span>
                        <span className="block text-sm text-road">{t(`roadClass.${item.road_class}`)}, {item.district}</span>
                      </span>
                      <span className="col-start-2 row-start-2 text-sm md:col-start-auto md:row-start-auto">
                        <span className="block">{item.owner}</span>
                        {item.maintainer !== item.owner && <span className="block text-road">{item.maintainer}</span>}
                      </span>
                      <span className="col-start-3 row-start-1 text-right font-condensed text-xl font-semibold tabular md:col-start-auto md:row-start-auto">{formatNumber(item.score, 1)}</span>
                      <span className="col-start-2 col-end-4 md:col-auto"><BreakdownBar item={item} /></span>
                      <span className="col-start-2 col-end-4 text-sm md:col-auto">
                        {item.recommended_action && <span className="block">{item.recommended_action}</span>}
                        {item.refer_to.length > 0 && <span className="block text-road">{t('priority.referTo', { agencies: listFormat(item.refer_to) })}</span>}
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
            </div>
          </div>
          <div className="print:hidden">
            <MiniMap items={items} hovered={hovered} onHover={setHovered} onOpen={(id) => navigate(`/analysis/${id}`)} />
            <p className="mt-2 text-sm text-road">{t('priority.miniMapHint', { count: ids.length })}</p>
          </div>
        </div>
      )}
    </div>
  )
}
