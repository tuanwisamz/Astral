import 'leaflet/dist/leaflet.css'

import { useQueries, useQuery } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MapContainer, TileLayer } from 'react-leaflet'
import { useSearchParams } from 'react-router'

import { isStaff, useApi, useAuthState } from '../app/auth'
import { Drawer, type Selection } from '../components/incident/Drawer'
import {
  BboxWatcher,
  FitTo,
  HighlightLayer,
  IncidentLayer,
  MapClick,
  PredictionLayer,
  SegmentLayer,
  WarningLayer,
} from '../components/map/layers'
import { Legend } from '../components/map/Legend'
import { HazardIcon } from '../components/ui/HazardIcon'
import { DemoBadge, ErrorBox } from '../components/ui/Status'
import { useToast } from '../components/ui/Toast'
import { ApiError } from '../lib/api'
import { HAZARD_TYPES, HAZARDS, type HazardType } from '../lib/hazards'
import type {
  FeatureCollection,
  IncidentProps,
  LineString,
  LocateResult,
  Point,
  Polygonal,
  PredictionProps,
  RiskLevel,
  SegmentProps,
  WarningProps,
} from '../lib/types'

const TILE_URL: string = import.meta.env.VITE_MAP_TILE_URL ?? 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const UTP: [number, number] = [4.3826, 100.9704] // focus area: UTP Seri Iskandar (plan A2)
const OPEN = 'REPORTED,VERIFIED,ASSIGNED,MITIGATED'
const LEVELS: RiskLevel[] = ['LOW', 'MEDIUM', 'HIGH', 'VERY_HIGH']
const LOCATE_MIN_ZOOM = 14
type Mode = 'current' | 'prediction'

const select = 'min-h-11 rounded border border-road bg-kerb px-2'

export default function LiveMap() {
  const { t } = useTranslation()
  const api = useApi()
  const auth = useAuthState()
  const toast = useToast()
  const [today] = useState(() => new Date().toISOString().slice(0, 10))
  const staff = isStaff(auth.role)
  const canEdit = auth.role === 'officer' || auth.role === 'admin' || auth.role === 'dev'
  const [params, setParams] = useSearchParams()
  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value === null || value === '') next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }

  const mode: Mode = staff && params.get('mode') === 'prediction' ? 'prediction' : 'current'
  const types = (params.get('types') ?? HAZARD_TYPES.join(',')).split(',').filter((x): x is HazardType => (HAZARD_TYPES as string[]).includes(x))
  const horizon = params.get('horizon') === '30' ? 30 : 7
  const minLevel = (params.get('level') as RiskLevel) || 'MEDIUM'
  const showResolved = params.get('resolved') === '1'
  const hideDemo = params.get('demo') === '0'
  const showWarnings = params.get('warnings') !== '0'
  const source = params.get('source') ?? ''
  const roadClass = params.get('class') ?? ''
  const since = params.get('since') ?? ''
  const highlightIds = useMemo(() => {
    const raw = params.get('highlight') ?? params.get('segment') ?? ''
    return raw.split(',').map(Number).filter((n) => Number.isInteger(n) && n > 0).slice(0, 20)
  }, [params])

  const [view, setView] = useState<{ bbox: string; zoom: number } | null>(null)
  const [selection, setSelection] = useState<Selection | null>(null)
  const onBbox = useCallback((bbox: string, zoom: number) => setView({ bbox, zoom }), [])
  const bbox = view?.bbox ?? null
  const typeParam = types.join(',')

  const incidents = useQuery({
    queryKey: ['map-incidents', bbox, typeParam, showResolved, hideDemo, source, roadClass, since],
    queryFn: () => api<FeatureCollection<Point, IncidentProps>>('/map/incidents', {
      params: { bbox, types: typeParam, status: showResolved ? `${OPEN},RESOLVED` : OPEN, include_synthetic: !hideDemo,
                source, road_class: roadClass, since },
    }),
    enabled: Boolean(bbox) && mode === 'current' && types.length > 0,
    refetchInterval: 5000, // plan D6: a new public report shows up within 10 s
  })
  const segments = useQuery({
    queryKey: ['map-segments', bbox, view?.zoom],
    queryFn: () => api<FeatureCollection<LineString, SegmentProps>>('/map/segments', { params: { bbox, zoom: view?.zoom } }),
    enabled: Boolean(bbox) && staff && (view?.zoom ?? 0) >= 12,
  })
  const predictions = useQuery({
    queryKey: ['map-predictions', bbox, typeParam, horizon, minLevel],
    queryFn: () => api<FeatureCollection<LineString, PredictionProps>>('/map/predictions', {
      params: { bbox, types: typeParam, horizon, min_level: minLevel } }),
    enabled: Boolean(bbox) && mode === 'prediction' && types.length > 0,
  })
  const warnings = useQuery({
    queryKey: ['map-warnings'],
    queryFn: () => api<FeatureCollection<Polygonal, WarningProps>>('/map/layers/warnings'),
    enabled: showWarnings,
    staleTime: 300_000,
  })
  const highlighted = useQueries({
    queries: staff ? highlightIds.map((id) => ({
      queryKey: ['segment', id],
      queryFn: () => api<{ geometry: LineString }>(`/segments/${id}`),
      staleTime: 600_000,
    })) : [],
  })
  const highlightLines = highlighted.map((h) => h.data?.geometry.coordinates).filter((c): c is [number, number][] => Boolean(c))
  // Refit only when the set of highlighted roads changes, not on every poll.
  const fitKey = `${highlightIds.join(',')}:${highlightLines.length}`
  // oxlint-disable-next-line react-hooks/exhaustive-deps -- keyed on fitKey on purpose
  const fitCoords = useMemo(() => (highlightLines.length ? highlightLines.flat() : null), [fitKey])

  async function onMapClick(lat: number, lng: number, zoom: number) {
    if (selection) { setSelection(null); return }
    if (zoom < LOCATE_MIN_ZOOM) return
    try {
      const road = await api<LocateResult>('/segments/locate', { params: { lat, lng } })
      setSelection({ kind: 'road', props: road })
    } catch (err) {
      if (err instanceof ApiError && err.code === 'NOT_ON_ROAD') toast(t('map.noRoadHere'))
    }
  }

  const toggleType = (h: HazardType) =>
    set('types', (types.includes(h) ? types.filter((x) => x !== h) : [...types, h]).join(',') || 'NONE')
  const error = incidents.error ?? segments.error ?? predictions.error
  const demoModel = predictions.data?.features.some((f) => f.properties.trained_on_demo_data)
  const truncated = incidents.data?.meta?.truncated || segments.data?.meta?.truncated

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-hairline bg-kerb px-4 py-2">
        {staff && (
          <div role="radiogroup" aria-label={t('map.mode')} className="inline-flex rounded border border-asphalt p-0.5" data-tour="mode">
            {(['current', 'prediction'] as const).map((m) => (
              <button key={m} type="button" role="radio" aria-checked={mode === m} onClick={() => set('mode', m === 'current' ? null : m)}
                className={`min-h-10 rounded-[3px] px-4 font-medium ${mode === m ? 'bg-asphalt text-kerb' : 'text-asphalt hover:bg-concrete'}`}>
                {t(`map.${m}`)}
              </button>
            ))}
          </div>
        )}
        <div role="group" aria-label={t('map.hazards')} className="flex flex-wrap gap-2">
          {HAZARD_TYPES.map((h) => {
            const on = types.includes(h)
            return (
              <button key={h} type="button" aria-pressed={on} onClick={() => toggleType(h)}
                className={`inline-flex min-h-11 items-center gap-2 rounded-full border px-3 ${on ? 'border-asphalt bg-kerb' : 'border-dashed border-road bg-concrete text-road'}`}>
                <span className={on ? '' : 'opacity-40'}><HazardIcon type={h} size={18} /></span>
                {t(HAZARDS[h].labelKey)}
              </button>
            )
          })}
        </div>
        {mode === 'prediction' ? (
          <>
            <label className="inline-flex items-center gap-2">{t('map.horizon')}
              <select className={select} value={horizon} onChange={(e) => set('horizon', e.target.value === '30' ? '30' : null)}>
                <option value={7}>{t('map.days', { count: 7 })}</option>
                <option value={30}>{t('map.days', { count: 30 })}</option>
              </select>
            </label>
            <label className="inline-flex items-center gap-2">{t('map.minLevel')}
              <select className={select} value={minLevel} onChange={(e) => set('level', e.target.value === 'MEDIUM' ? null : e.target.value)}>
                {LEVELS.map((l) => <option key={l} value={l}>{t('map.levelAndAbove', { level: t(`risk.${l}`) })}</option>)}
              </select>
            </label>
          </>
        ) : (
          <details className="relative">
            <summary className="inline-flex min-h-11 cursor-pointer items-center rounded border border-road px-3">{t('map.filters')}</summary>
            <div className="absolute z-[1200] mt-1 w-72 space-y-3 rounded border border-hairline bg-kerb p-3 shadow-lg">
              <label className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={showResolved} onChange={(e) => set('resolved', e.target.checked ? '1' : null)} />{t('map.showResolved')}</label>
              <label className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={hideDemo} onChange={(e) => set('demo', e.target.checked ? '0' : null)} />{t('map.hideDemo')}</label>
              <label className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={showWarnings} onChange={(e) => set('warnings', e.target.checked ? null : '0')} />{t('map.showWarnings')}</label>
              {staff && (
                <>
                  <label className="block text-sm">{t('map.source')}
                    <select className={`${select} mt-1 w-full`} value={source} onChange={(e) => set('source', e.target.value)}>
                      <option value="">{t('map.anySource')}</option>
                      {['PUBLIC', 'NEWS', 'OFFICER'].map((s) => <option key={s} value={s}>{t(`source.${s}`)}</option>)}
                    </select>
                  </label>
                  <label className="block text-sm">{t('drawer.class')}
                    <select className={`${select} mt-1 w-full`} value={roadClass} onChange={(e) => set('class', e.target.value)}>
                      <option value="">{t('map.anyClass')}</option>
                      {['FEDERAL', 'STATE', 'MUNICIPAL', 'EXPRESSWAY'].map((c) => <option key={c} value={c}>{t(`roadClass.${c}`)}</option>)}
                    </select>
                  </label>
                </>
              )}
              <label className="block text-sm">{t('map.since')}
                <input type="date" className={`${select} mt-1 w-full`} value={since} max={today} onChange={(e) => set('since', e.target.value)} />
              </label>
            </div>
          </details>
        )}
      </div>
      {mode === 'prediction' && demoModel && (
        <p className="flex items-center gap-2 border-b border-hairline bg-kerb px-4 py-2 text-sm"><DemoBadge />{t('map.demoModel')}</p>
      )}
      {(error || types.length === 0 || truncated) && (
        <div className="border-b border-hairline bg-kerb p-3">
          {error ? <ErrorBox error={error} /> : types.length === 0 ? <p className="text-sm text-road">{t('map.noneShown')}</p>
            : <p className="text-sm text-road">{t('map.truncated')}</p>}
        </div>
      )}
      <div className="relative min-h-0 flex-1">
        <MapContainer center={UTP} zoom={14} preferCanvas className="h-full w-full">
          <TileLayer url={TILE_URL} attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' />
          <BboxWatcher onChange={onBbox} />
          <MapClick onClick={onMapClick} />
          <FitTo coords={fitCoords} />
          {showWarnings && warnings.data && <WarningLayer data={warnings.data} />}
          {segments.data && <SegmentLayer data={segments.data} onSelect={(props) => setSelection({ kind: 'segment', props })} />}
          {highlightLines.length > 0 && <HighlightLayer lines={highlightLines} />}
          {mode === 'prediction' && predictions.data && <PredictionLayer data={predictions.data} onSelect={(props) => setSelection({ kind: 'prediction', props })} />}
          {mode === 'current' && incidents.data && <IncidentLayer data={incidents.data} onSelect={(props) => setSelection({ kind: 'incident', props })} />}
        </MapContainer>
        <Legend mode={mode} roadHint />
        {selection && <Drawer selection={selection} staff={staff} canEdit={canEdit} onClose={() => setSelection(null)} />}
      </div>
    </div>
  )
}
